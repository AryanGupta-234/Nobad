import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/engine/rpc.dart';

/// A transport whose other end is this test: lines sent are recorded, replies are pushed by [reply].
class FakeTransport implements Transport {
  FakeTransport({this.autoReply});
  final _in = StreamController<String>();
  final sent = <Map<String, Object?>>[];
  final Object? Function(String method, Map params)? autoReply;
  var closed = false;

  @override
  Stream<String> get lines => _in.stream;

  @override
  void send(String line) {
    if (closed) throw const EngineOffline();
    final m = jsonDecode(line) as Map<String, Object?>;
    sent.add(m);
    final r = autoReply?.call(m['method'] as String, (m['params'] ?? {}) as Map);
    if (r != null) scheduleMicrotask(() => push({'jsonrpc': '2.0', 'id': m['id'], 'result': r}));
  }

  void push(Object msg) {
    if (!closed) _in.add(msg is String ? msg : jsonEncode(msg));
  }

  void drop() {
    closed = true;
    _in.close();
  }

  @override
  Future<void> close() async {
    if (!closed) drop();
  }
}

Object? engineReplies(String method, Map params) => switch (method) {
      'hello' => {'protocol': 1, 'app': 'NOBAD Find', 'version': '0.7.0'},
      'subscribe' => {'events': ['show', 'status']},
      'status' => {'level': 'gentle', 'reason': 'Gentle: you are using the PC', 'phase': 'watching', 'files': 1234},
      'search' => {
          'results': [
            {'id': 9, 'name': 'a.pdf', 'dir': r'C:\x', 'kind': 'pdf', 'size': 10, 'why': ['name matches']},
            {'id': 'bad', 'name': 'no id'},
            'not a row',
          ],
          'ms': 7,
        },
      'open' => {'ok': true},
      'thumbnail' => {'url': 'data:image/png;base64,${base64Encode([1, 2, 3])}'},
      _ => null,
    };

void main() {
  group('RpcSession', () {
    test('matches replies to requests by id, and errors become RpcException', () async {
      final t = FakeTransport();
      final s = RpcSession(t, onEvent: (_) {});
      final a = s.call('one');
      final b = s.call('two', {'x': 1});
      expect(t.sent.map((m) => m['id']), [1, 2]);
      expect(t.sent[1]['params'], {'x': 1});
      expect(t.sent[0]['jsonrpc'], '2.0');
      t.push({'jsonrpc': '2.0', 'id': 2, 'result': 'second'});
      t.push({'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32601, 'message': 'Method not found'}});
      expect(await b, 'second');
      await expectLater(a, throwsA(isA<RpcException>().having((e) => e.code, 'code', -32601)));
    });

    test('ignores junk lines and delivers events', () async {
      final t = FakeTransport();
      final got = <EngineEvent>[];
      final s = RpcSession(t, onEvent: got.add);
      t.push('this is not json');
      t.push('[1,2]');
      t.push({'jsonrpc': '2.0', 'id': 77, 'result': 'nobody asked'});
      t.push({'jsonrpc': '2.0', 'method': 'status', 'params': {'files': 5, 'phase': 'names'}});
      t.push({'jsonrpc': '2.0', 'method': 'show', 'params': {'what': 'bar'}});
      t.push({'jsonrpc': '2.0', 'method': 'from_the_future', 'params': {}});
      await pumpEventQueue();
      expect(got, hasLength(2));
      expect((got[0] as StatusEvent).status.files, 5);
      expect((got[1] as ShowEvent).what, 'bar');
      expect(s.isOpen, isTrue);
    });

    test('a dropped connection fails what was waiting', () async {
      final t = FakeTransport();
      final s = RpcSession(t, onEvent: (_) {});
      final a = s.call('search');
      t.drop();
      await expectLater(a, throwsA(isA<EngineOffline>()));
      await s.done;
      await expectLater(s.call('again'), throwsA(isA<EngineOffline>()));
    });

    test('times out', () async {
      final s = RpcSession(FakeTransport(), onEvent: (_) {});
      await expectLater(s.call('slow', const {}, const Duration(milliseconds: 10)), throwsA(isA<RpcException>()));
    });
  });

  group('EngineClient', () {
    test('hello, subscribe, typed calls, events', () async {
      final t = FakeTransport(autoReply: engineReplies);
      final c = EngineClient(() async => t, backoff: const [Duration(milliseconds: 1)])..start();
      await pumpEventQueue();
      expect(c.link.value, Link.connected);
      expect(t.sent.map((m) => m['method']).take(2), ['hello', 'subscribe']);
      expect((t.sent[1]['params'] as Map)['events'], EngineEvent.mainWindow);
      expect(c.served, prototypeMethods); // a hello without `methods`: the prototype engine
      expect(c.lastStatus?.files, 1234);
      final a = await c.search('a', filters: const SearchFilters(kind: 'pdf'));
      expect((t.sent.last['params'] as Map)['filters'], {'kind': 'pdf', 'modified': '', 'size': '', 'folder': '', 'sort': ''});
      expect(a.results.single.id, 9); // rows without a whole-number id are dropped
      expect(a.ms, 7);
      expect((await c.open(9)).ok, isTrue);
      expect(await c.thumbnail(9), Uint8List.fromList([1, 2, 3]));
      final asked = t.sent.where((m) => m['method'] == 'thumbnail').length;
      await c.thumbnail(9); // cached
      expect(t.sent.where((m) => m['method'] == 'thumbnail').length, asked);
      c.dispose();
    });

    test('reconnects with backoff after the engine goes away', () async {
      var tries = 0;
      final transports = <FakeTransport>[];
      final c = EngineClient(() async {
        tries++;
        if (tries == 2) throw const EngineOffline(); // engine restarting
        final t = FakeTransport(autoReply: engineReplies);
        transports.add(t);
        return t;
      }, backoff: const [Duration(milliseconds: 1)])
        ..start();
      await pumpEventQueue();
      expect(c.link.value, Link.connected);
      transports.single.drop();
      await pumpEventQueue();
      await expectLater(c.search('x'), throwsA(isA<EngineOffline>()));
      for (var i = 0; i < 50 && c.link.value != Link.connected; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 5));
      }
      expect(c.link.value, Link.connected);
      expect(tries, 3);
      expect((await c.search('x')).results, hasLength(1));
      c.dispose();
    });

    test('refuses an engine with another protocol', () async {
      final t = FakeTransport(autoReply: (m, p) => m == 'hello' ? {'protocol': 99} : null);
      final c = EngineClient(() async => t)..start();
      await pumpEventQueue();
      expect(c.link.value, Link.incompatible);
      expect(t.sent.where((m) => m['method'] == 'search'), isEmpty);
      c.dispose();
    });
  });

  group('framing and parsing', () {
    test('LineSplitterBytes splits, joins partial lines and caps', () {
      final s = LineSplitterBytes(cap: 16);
      expect(s.feed(Uint8List.fromList(utf8.encode('{"a":1}\n{"b"'))), ['{"a":1}']);
      expect(s.feed(Uint8List.fromList(utf8.encode(':"é"}\r\n\n'))), ['{"b":"é"}']);
      expect(() => s.feed(Uint8List.fromList(List.filled(17, 0x41))), throwsA(isA<LineTooLong>()));
    });

    test('image data URLs only', () {
      expect(decodeImageDataUrl('data:image/png;base64,AQID'), [1, 2, 3]);
      expect(decodeImageDataUrl('data:text/html;base64,AQID'), isNull);
      expect(decodeImageDataUrl('https://example.com/x.png'), isNull);
      expect(decodeImageDataUrl('data:image/png;base64,%%%'), isNull);
      expect(decodeImageDataUrl(''), isNull);
      expect(decodeImageDataUrl(42), isNull);
    });

    test('models survive odd values', () {
      final r = FileResult.fromJson({'id': 3, 'name': 7, 'kind': null, 'size': 'big', 'why': ['a', 1], 'mtime': 1.5});
      expect(r!.name, '');
      expect(r.kind, 'other');
      expect(r.size, isNull);
      expect(r.why, ['a']);
      expect(FileResult.fromJson({'name': 'x'}), isNull);
      expect(SearchAnswer.fromJson('nope').error, isNotEmpty);
      final s = EngineStatus.fromJson({'files': -5, 'level': 'paused', 'paused': 'on battery'});
      expect(s.files, 0);
      expect(s.phaseLabel, 'Paused · on battery');
      expect(humanSize(482113), '471 KB');
      expect(humanSize(null), '');
    });
  });
}
