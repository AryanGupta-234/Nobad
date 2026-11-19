import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_vpn_ui/engine/pipe_client.dart';
import 'package:nobad_vpn_ui/engine/rpc.dart';

import '../support/support.dart';

Map<String, Object?> j(String line) => jsonDecode(line) as Map<String, Object?>;

/// An engine that answers hello / subscribe / state / ui_* like the real one.
FakeTransport engineTransport({int protocol = 1, Map<String, Object?>? refuse}) {
  final t = FakeTransport();
  t.onSend = (line) {
    final m = j(line);
    final id = m['id'];
    Object? result;
    switch (m['method']) {
      case 'hello':
        if (refuse != null) {
          scheduleMicrotask(() => t.reply(jsonEncode({'jsonrpc': '2.0', 'id': null, 'error': refuse})));
          return;
        }
        result = {'protocol': protocol, 'app': 'NOBAD VPN', 'version': '2.0.0', 'pid': 42,
            'methods': ['hello', 'subscribe', 'state', 'ui_shown', 'ui_hidden', 'connect']};
      case 'subscribe':
        result = {'events': (m['params'] as Map)['events']};
      case 'state':
        result = {'connected': false, 'regions': <Object?>[], 'settings': <String, Object?>{}};
      default:
        result = {'ok': true};
    }
    scheduleMicrotask(() => t.reply(jsonEncode({'jsonrpc': '2.0', 'id': id, 'result': result})));
  };
  return t;
}

void main() {
  group('RpcSession', () {
    test('matches replies by id, in any order, and passes events on', () async {
      final t = FakeTransport();
      final events = <EngineEvent>[];
      final s = RpcSession(t, onEvent: events.add);
      final a = s.call('state');
      final b = s.call('connect', {'name': 'JP'});
      t.reply('{"jsonrpc":"2.0","method":"traffic","params":{"rx_bps":1}}');
      t.reply('{"jsonrpc":"2.0","id":2,"result":{"ok":true}}');
      t.reply('{"jsonrpc":"2.0","id":1,"result":{"connected":true}}');
      expect(await b, {'ok': true});
      expect(await a, {'connected': true});
      expect(events.single.name, 'traffic');
      expect(j(t.sent[1]), {'jsonrpc': '2.0', 'id': 2, 'method': 'connect', 'params': {'name': 'JP'}});
    });

    test('an error reply is an RpcException with the engine\'s sentence', () async {
      final t = FakeTransport();
      final s = RpcSession(t, onEvent: (_) {});
      final f = s.call('connect', {'name': '..'});
      t.reply('{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"\'name\' has an unexpected form"}}');
      await expectLater(f, throwsA(isA<RpcException>().having((e) => e.code, 'code', -32602)));
    });

    test('a refusal (id null) fails every waiting call; a closed pipe means offline', () async {
      final t = FakeTransport();
      final s = RpcSession(t, onEvent: (_) {});
      final f = s.call('hello');
      t.reply('{"jsonrpc":"2.0","id":null,"error":{"code":-32001,"message":"This program may not control NOBAD VPN."}}');
      await expectLater(f, throwsA(isA<RpcException>().having((e) => e.code, 'code', -32001)));
      final g = s.call('state');
      await t.close();
      await expectLater(g, throwsA(isA<EngineOffline>()));
      await expectLater(s.call('state'), throwsA(isA<EngineOffline>()));
    });

    test('garbage lines are ignored', () async {
      final t = FakeTransport();
      final s = RpcSession(t, onEvent: (_) => fail('no event'));
      final f = s.call('state');
      t.reply('not json');
      t.reply('[1,2]');
      t.reply('{"jsonrpc":"2.0","id":1,"result":1}');
      expect(await f, 1);
    });
  });

  group('EngineClient', () {
    test('start-up order: hello, subscribe, state, then the window report', () async {
      final t = engineTransport();
      final c = EngineClient(() async => t, subscribeTo: const ['state', 'show'], window: 'mini');
      final states = <EngineEvent>[];
      c.events.listen(states.add);
      c.start();
      await pumpEventQueue();
      expect(c.link.value, Link.connected);
      expect([for (final l in t.sent) j(l)['method']], ['hello', 'subscribe', 'state', 'ui_shown']);
      expect(j(t.sent[3])['params'], {'window': 'mini'});
      expect(states.single.name, 'state');
      expect(c.engineVersion, '2.0.0');
      await expectLater(c.call('quit'), throwsA(isA<RpcException>().having((e) => e.code, 'code', -32601)));
      c.dispose();
    });

    test('another protocol version: incompatible, never connected', () async {
      final c = EngineClient(() async => engineTransport(protocol: 2));
      c.start();
      await pumpEventQueue();
      expect(c.link.value, Link.incompatible);
      c.dispose();
    });

    test('a refused program is told so and backs off', () async {
      final c = EngineClient(() async => engineTransport(refuse: {'code': -32001, 'message': 'no'}));
      c.start();
      await pumpEventQueue();
      expect(c.link.value, Link.refused);
      c.dispose();
    });

    test('no engine: offline, and calls fail as offline', () async {
      final c = EngineClient(() async => throw const EngineOffline(), backoff: const [Duration(milliseconds: 1)]);
      c.start();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(c.link.value, Link.offline);
      await expectLater(c.call('state'), throwsA(isA<EngineOffline>()));
      c.dispose();
    });
  });

  group('framing', () {
    test('lines split across reads, CRLF, and the 1 MiB cap', () {
      final s = LineSplitterBytes(cap: 8);
      expect(s.feed(Uint8List.fromList(utf8.encode('{"a"'))), isEmpty);
      expect(s.feed(Uint8List.fromList(utf8.encode(':1}\r\n{}\n'))), ['{"a":1}', '{}']);
      expect(() => s.feed(Uint8List.fromList(utf8.encode('123456789'))), throwsA(isA<LineTooLong>()));
    });
  });

  group('the pipe', () {
    test('its name carries the user and never mixes the dev engine with the real one', () {
      const sid = 'S-1-5-21-1-2-3-1001';
      expect(enginePipeName(sid: sid), r'\\.\pipe\NOBADVPN-S-1-5-21-1-2-3-1001');
      expect(enginePipeName(sid: sid, dev: true), r'\\.\pipe\NOBADVPN-dev-S-1-5-21-1-2-3-1001');
    });

    test('only an elevated owner may be the engine (the dev engine: this user)', () {
      const me = 'S-1-5-21-1-2-3-1001';
      expect(ownerAllowed('S-1-5-32-544', dev: false, me: me), isTrue); // Administrators
      expect(ownerAllowed('S-1-5-18', dev: false, me: me), isTrue); // SYSTEM
      expect(ownerAllowed(me, dev: false, me: me), isFalse); // a program running as this user took the name
      expect(ownerAllowed(null, dev: false, me: me), isFalse);
      expect(ownerAllowed(me, dev: true, me: me), isTrue);
      expect(ownerAllowed('S-1-5-32-544', dev: true, me: me), isFalse);
    });
  });
}
