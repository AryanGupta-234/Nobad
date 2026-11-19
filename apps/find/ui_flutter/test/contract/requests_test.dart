// Every request in apps/find/contract/transcripts, made with this UI's typed client: what the client sends must
// mean the same as the transcript's `send` line, and the transcript's answer (result or error) must come back as
// the typed result or an RpcException with the same code.
import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/rpc.dart';

import 'transcripts_test.dart' show readTranscript, transcripts;

/// What a request means: absent, null and "" are all "not set"; ui_shown/ui_hidden default to the main window.
Map<String, Object?> normal(String method, Object? params) {
  Object? clean(Object? v) {
    if (v is! Map) return v;
    final out = <String, Object?>{};
    for (final e in v.entries) {
      final c = clean(e.value);
      if (c == null || c == '' || (c is Map && c.isEmpty)) continue;
      out[e.key as String] = c;
    }
    return out;
  }

  final m = params is Map ? Map<String, Object?>.from(clean(params) as Map) : <String, Object?>{'_': params};
  if ((method == 'ui_shown' || method == 'ui_hidden') && !m.containsKey('window')) m['window'] = 'main';
  if (method == 'search') m.remove('text');
  if (method == 'search' && !m.containsKey('channel')) m['channel'] = 'main'; // the contract's default
  return m;
}

/// The request through the typed client when there is a typed call for it, else as a raw call (the transcripts
/// also send deliberately wrong requests, which no typed call can make).
Future<Object?> make(EngineClient c, String m, Map<String, Object?> p) {
  final id = p['id'];
  switch (m) {
    case 'search' when p['filters'] == null || p['filters'] is Map:
      final f = (p['filters'] as Map?) ?? const {};
      String s(String k) => f[k] is String ? f[k] as String : '';
      return c.search(
        p['text'] as String? ?? '',
        filters: SearchFilters(
          kind: s('kind'),
          modified: s('modified'),
          size: s('size'),
          folder: s('folder'),
          sort: s('sort'),
        ),
      );
    case 'open' when id is int:
      return c.open(id);
    case 'reveal' when id is int:
      return c.reveal(id);
    case 'forget' when id is int:
      return c.forget(id);
    case 'path_of' when id is int:
      return c.pathOf(id);
    case 'thumbnail' when id is int:
      c.clearThumbs();
      return c.thumbnail(id);
    case 'here_folder':
      return c.hereFolder();
    case 'to_main' when p['text'] is String:
      return c.toMain(p['text'] as String);
    case 'status':
      return c.status();
    case 'status_full':
      return c.statusFull();
    case 'pause_for' when p['seconds'] is int && (p['seconds'] as int) >= 1:
      return c.pauseFor(Duration(seconds: p['seconds'] as int));
    case 'resume':
      return c.resume();
    case 'learned_apps':
      return c.learnedApps();
    case 'reset_learned' when p['exe'] == null || p['exe'] is String:
      return c.resetLearned(p['exe'] as String?);
    case 'hardware':
      return c.hardware();
    case 'get_settings':
      return c.getSettings();
    case 'set_settings' when p['changes'] is Map:
      return c.setSettings(Map<String, Object?>.from(p['changes'] as Map));
    case 'pick_folder':
      return c.pickFolder();
    case 'wsearch_state':
      return c.wsearchState();
    case 'use_instead_of_windows_search' when p['on'] is bool:
      return c.useInsteadOfWindowsSearch(p['on'] as bool);
    case 'download_model':
      return c.downloadModel('meaning');
    case 'download_photo_model':
      return c.downloadModel('photo');
    case 'rescan':
      return c.rescan();
    case 'wipe' when p['confirm'] is String:
      return c.wipe(p['confirm'] as String);
    case 'quit' when p['confirm'] == 'QUIT':
      return c.quit();
    case 'ui_shown':
      return c.uiShown(p['window'] as String? ?? 'main');
    case 'ui_hidden':
      return c.uiHidden(p['window'] as String? ?? 'main');
    case 'scope_info':
      return c.scopeInfo();
    case 'turbo_state':
      return c.turboState();
    case 'turbo_set' when p['on'] is bool:
      return c.turboSet(p['on'] as bool);
  }
  return c.call(m, p);
}

void main() {
  for (final name in transcripts) {
    test('$name: the client asks the same and reads the answers', () async {
      final lines = readTranscript(name);
      final hello = readTranscript('01-connect-and-search.jsonl')
          .map((l) => l['recv'])
          .whereType<Map>()
          .firstWhere((r) => r['result'] is Map && (r['result'] as Map).containsKey('methods'))['result'];
      // answers by transcript id, for the request being replayed
      final byId = <Object?, Map>{};
      for (final l in lines) {
        final r = l['recv'];
        if (r is Map && r.containsKey('id') && r['id'] != null) byId[r['id']] = r;
      }
      Object? want; // the transcript id of the request being replayed
      var starting = true;
      late FakeTransport t;
      t = FakeTransport(
        onSend: (m) {
          if (starting) {
            final r = switch (m['method']) {
              'hello' => hello,
              'subscribe' => {'events': <String>[]},
              'status' => {'level': 'gentle', 'reason': 'r', 'phase': 'text', 'files': 1, 'paused': ''},
              _ => {'ok': true},
            };
            scheduleMicrotask(() => t.push({'jsonrpc': '2.0', 'id': m['id'], 'result': r}));
            return;
          }
          final r = byId[want];
          if (r == null) return;
          scheduleMicrotask(() => t.push({...r, 'id': m['id']}));
        },
      );
      final c = EngineClient(() async => t, backoff: const [Duration(seconds: 5)])..start();
      await pumpEventQueue();
      expect(c.link.value, Link.connected);
      starting = false;
      var replayed = 0;
      for (final l in lines) {
        final send = l['send'];
        if (send is! Map) continue;
        final method = send['method'] as String;
        final params = (send['params'] is Map ? Map<String, Object?>.from(send['params'] as Map) : <String, Object?>{});
        want = send['id'];
        final before = t.sent.length;
        final answer = byId[want];
        Object? got;
        Object? error;
        try {
          got = await make(c, method, params).timeout(const Duration(seconds: 2));
        } on RpcException catch (e) {
          error = e;
        } on TimeoutException {
          error = 'no answer';
        }
        final asked = t.sent.length > before ? t.sent.last : null;
        if (answer != null && answer['error'] is Map) {
          final code = (answer['error'] as Map)['code'];
          expect(error, isA<RpcException>().having((e) => e.code, 'code', code), reason: '$name $method');
        } else if (asked != null) {
          expect(error, isNull, reason: '$name $method: $error');
        }
        if (asked != null) {
          expect(asked['method'], method, reason: name);
          expect(normal(method, asked['params']), normal(method, send['params']), reason: '$name $method');
          replayed++;
        } else {
          // refused before asking: only a method the engine doesn't list
          expect(c.serves(method), isFalse, reason: '$name $method');
        }
        if (got == null && error == null && answer == null) continue;
      }
      expect(replayed, greaterThan(0));
      c.dispose();
    });
  }
}

/// A transport whose other end is this test.
class FakeTransport implements Transport {
  FakeTransport({required this.onSend});
  final void Function(Map<String, Object?> msg) onSend;
  final _in = StreamController<String>();
  final sent = <Map<String, Object?>>[];

  @override
  Stream<String> get lines => _in.stream;

  @override
  void send(String line) {
    final m = jsonDecode(line) as Map<String, Object?>;
    sent.add(m);
    onSend(m);
  }

  void push(Object msg) => _in.add(jsonEncode(msg));

  @override
  Future<void> close() async => _in.close();
}
