import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/engine_api.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/rpc.dart';
import 'package:nobad_find/engine/wiring.dart';
import 'package:nobad_find/state/search_controller.dart';

import 'rpc_test.dart' show FakeTransport;

Object? fullEngine(String method, Map params) => switch (method) {
  'hello' => {
    'protocol': 1,
    'pid': 7,
    'methods': [
      'hello',
      'subscribe',
      'unsubscribe',
      'status',
      'status_full',
      'search',
      'set_settings',
      'ui_shown',
      'ui_hidden',
      'get_settings',
      'wipe',
      'rescan',
      'path_of',
    ],
  },
  'subscribe' || 'unsubscribe' => {'events': <String>[]},
  'status' => {'level': 'gentle', 'reason': 'r', 'phase': 'text', 'files': 1, 'paused': ''},
  'get_settings' => {'theme': 'dark'},
  'wipe' || 'rescan' || 'ui_shown' || 'ui_hidden' => {'ok': true, 'error': ''},
  _ => null,
};

void main() {
  test('no engine: every call fails as offline, nothing is made up', () async {
    final c = EngineClient(() async => throw const EngineOffline(), backoff: const [Duration(seconds: 1)])..start();
    final e = PipeEngine(c);
    await pumpEventQueue();
    expect(e.link.value, Link.offline);
    await expectLater(e.getSettings(), throwsA(isA<EngineOffline>()));
    await expectLater(e.wipe('DELETE'), throwsA(isA<EngineOffline>()));
    await expectLater(e.rescan(), throwsA(isA<EngineOffline>()));
    await expectLater(e.pickFolder(), throwsA(isA<EngineOffline>()));
    await expectLater(e.statusFull(), throwsA(isA<EngineOffline>()));
    await expectLater(e.learnedApps(), throwsA(isA<EngineOffline>()));
    await expectLater(e.useInsteadOfWindowsSearch(true), throwsA(isA<EngineOffline>()));
    await expectLater(e.pathOf(1), throwsA(isA<EngineOffline>()));
    e.dispose();
  });

  test('a method the engine does not list fails with -32601, without asking it', () async {
    final t = FakeTransport(autoReply: fullEngine);
    final c = EngineClient(() async => t, backoff: const [Duration(milliseconds: 1)])..start();
    final e = PipeEngine(c);
    await pumpEventQueue();
    await expectLater(e.hardware(), throwsA(isA<RpcException>().having((x) => x.code, 'code', -32601)));
    expect(t.sent.where((m) => m['method'] == 'hardware'), isEmpty);
    expect((await e.wipe('DELETE')).ok, isTrue);
    e.dispose();
  });

  test('ui_shown goes out on connect only while the window is on screen', () async {
    final t = FakeTransport(autoReply: fullEngine);
    final c = EngineClient(() async => t, window: 'bar', backoff: const [Duration(milliseconds: 1)])..start();
    await pumpEventQueue();
    expect(t.sent.where((m) => m['method'] == 'ui_shown'), isEmpty); // the bar starts hidden
    c.dispose();

    final t2 = FakeTransport(autoReply: fullEngine);
    final c2 = EngineClient(() async => t2, backoff: const [Duration(milliseconds: 1)]);
    unawaited(c2.uiHidden('main').catchError((Object _) {})); // hidden before it even connected
    c2.start();
    await pumpEventQueue();
    expect(t2.sent.where((m) => m['method'] == 'ui_shown'), isEmpty);
    c2.dispose();
  });

  test('window, details and settings calls go out one at a time, in order', () async {
    late FakeTransport t;
    t = FakeTransport(
      autoReply: (m, p) {
        if (m == 'set_settings') return null; // answered by hand below
        return fullEngine(m, p);
      },
    );
    final c = EngineClient(() async => t, backoff: const [Duration(milliseconds: 1)])..start();
    await pumpEventQueue();
    final f1 = c.setSettings({'theme': 'light'});
    final f2 = c.setSettings({'theme': 'dark'});
    await pumpEventQueue();
    expect(t.sent.where((m) => m['method'] == 'set_settings'), hasLength(1)); // the second waits
    final first = t.sent.lastWhere((m) => m['method'] == 'set_settings');
    t.push({
      'jsonrpc': '2.0',
      'id': first['id'],
      'result': {
        'changed': ['theme'],
        'settings': {'theme': 'light'},
      },
    });
    await pumpEventQueue();
    final second = t.sent.lastWhere((m) => m['method'] == 'set_settings');
    expect((second['params'] as Map)['changes'], {'theme': 'dark'});
    t.push({
      'jsonrpc': '2.0',
      'id': second['id'],
      'result': {
        'changed': ['theme'],
        'settings': {'theme': 'dark'},
      },
    });
    expect((await f1).settings.text('theme'), 'light');
    expect((await f2).settings.text('theme'), 'dark');

    unawaited(c.uiHidden('main'));
    unawaited(c.uiShown('main'));
    await pumpEventQueue();
    final window = [
      for (final m in t.sent)
        if (m['method'] == 'ui_hidden' || m['method'] == 'ui_shown') m['method'],
    ];
    expect(window.last, 'ui_shown'); // the newest wish is what the engine ends up with
    c.dispose();
  });

  test('a reply to a request the engine could not read (id null) fails what is waiting at once', () async {
    final t = FakeTransport(autoReply: (m, p) => m == 'search' ? null : fullEngine(m, p));
    final c = EngineClient(() async => t, backoff: const [Duration(milliseconds: 1)])..start();
    await pumpEventQueue();
    final f = c.search('x');
    await pumpEventQueue();
    t.push(
      jsonEncode({
        'jsonrpc': '2.0',
        'id': null,
        'error': {'code': -32700, 'message': 'not JSON'},
      }),
    );
    await expectLater(f, throwsA(isA<RpcException>().having((x) => x.code, 'code', -32700)));
    c.dispose();
  });

  test('a late answer to an older search is ignored', () async {
    final late = Completer<SearchAnswer>();
    final engine = _SlowSearch(late.future);
    final f = FindController(engine, debounce: Duration.zero);
    f.setText('old');
    await pumpEventQueue();
    engine.next = Future.value(const SearchAnswer(ms: 2));
    f.setText('new');
    await pumpEventQueue();
    expect(f.askedFor, 'new');
    late.complete(const SearchAnswer(ms: 99));
    await pumpEventQueue();
    expect(f.askedFor, 'new');
    expect(f.answer.ms, 2);
    f.dispose();
  });
}

class _SlowSearch extends _Unused {
  _SlowSearch(this.next);
  Future<SearchAnswer> next;
  @override
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none, String channel = 'main'}) =>
      next;
}

/// The rest of the interface, never called by these tests.
class _Unused implements EngineApi {
  @override
  Stream<EngineEvent> get events => const Stream.empty();
  @override
  dynamic noSuchMethod(Invocation invocation) => throw UnimplementedError();
}
