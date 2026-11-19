// Replays the engine's recorded contract sessions (apps/find/contract/transcripts, the same files the Python
// contract test replays) through this UI's models and its pipe client. `engine` and `note` lines are the engine's side and are skipped.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/models/settings.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/engine/rpc.dart';

import '../engine/rpc_test.dart' show FakeTransport;

typedef Line = Map<String, Object?>;

List<Line> readTranscript(String name) => [
      for (final l in File('../contract/transcripts/$name').readAsLinesSync())
        if (l.trim().isNotEmpty) jsonDecode(l) as Line,
    ];

final transcripts = [
  for (final f in Directory('../contract/transcripts').listSync()..sort((a, b) => a.path.compareTo(b.path)))
    if (f.path.endsWith('.jsonl')) f.uri.pathSegments.last,
];

/// (method, result) for every answered request, in order.
List<(String, Object?)> answers() {
  final out = <(String, Object?)>[];
  for (final t in transcripts) {
    final asked = <Object?, String>{};
    for (final l in readTranscript(t)) {
      final send = l['send'];
      if (send is Map) asked[send['id']] = send['method'] as String;
      final recv = l['recv'];
      if (recv is Map && recv.containsKey('result')) out.add((asked[recv['id']]!, recv['result']));
    }
  }
  return out;
}

void main() {
  test('there are transcripts', () => expect(transcripts, hasLength(greaterThanOrEqualTo(4))));

  test('every event the engine sends parses into a typed event', () {
    final seen = <String>{};
    for (final t in transcripts) {
      for (final l in readTranscript(t)) {
        final recv = l['recv'];
        if (recv is! Map || recv.containsKey('id')) continue;
        final method = recv['method'] as String;
        final e = EngineEvent.parse(method, recv['params']);
        expect(e, isNotNull, reason: '$t: $method');
        seen.add(method);
        switch (e) {
          case DownloadEvent():
            expect(['meaning', 'photo'], contains(e.id));
            expect(e.sizeMb, greaterThan(0));
          case ShowEvent():
            expect(['main', 'bar'], contains(e.what));
          case StatusFullEvent():
            expect(e.status.details, isNotNull);
            expect(e.status.details!.phases, isNotEmpty);
          case LevelEvent():
            expect(e.reason, isNotEmpty);
          default:
        }
      }
    }
    expect(seen, containsAll(['status', 'status_full', 'level', 'activity', 'download', 'notice', 'show', 'here',
        'quitting']));
  });

  test('every answer parses with the model the UI uses for it', () {
    for (final (method, r) in answers()) {
      switch (method) {
        case 'search':
          final a = SearchAnswer.fromJson(r);
          expect(a.error, isEmpty);
          for (final x in a.results) {
            expect(x.path, isNotEmpty);
          }
        case 'status':
          expect(EngineStatus.fromJson(r).levelLabel, isNotEmpty);
        case 'status_full':
          final d = EngineStatus.fromJson(r).details!;
          expect(d.phases.map((p) => p.id), containsAll(['names', 'text', 'watching']));
          expect(d.models.map((m) => m.id), containsAll(['meaning', 'photo', 'ocr']));
          expect(d.history, isNotEmpty);
        case 'get_settings':
          final s = Settings.fromJson(r);
          expect(s.text('theme'), anyOf('dark', 'light'));
          expect(s.flag('welcome_seen'), isTrue); // an engine without the key never shows the welcome again
        case 'set_settings':
          expect(SettingsChange.fromJson(r).settings.values, isNotEmpty);
        case 'learned_apps':
          expect(LearnedApp.listFromJson(r).single.bare, 'game');
        case 'hardware':
          expect(Hardware.fromJson(r)!.threads, 16);
        case 'wsearch_state':
          expect(WsearchState.fromJson(r).start, 'delayed-auto');
        case 'open' || 'reveal' || 'forget' || 'wipe' || 'quit' || 'rescan' || 'pause_for' || 'resume' ||
              'reset_learned' || 'download_model' || 'download_photo_model' || 'wsearch_set' ||
              'use_instead_of_windows_search':
          final a = ActionResult.fromJson(r);
          if (!a.ok) expect(a.error, isA<String>());
        case 'thumbnail':
          final url = (r as Map)['url'] as String;
          expect(url.isEmpty || decodeImageDataUrl(url) != null, isTrue);
        default:
      }
    }
  });

  test('the pipe client asks the way the contract says and reads what comes back', () async {
    final queue = <String, List<Object?>>{};
    for (final (m, r) in answers()) {
      (queue[m] ??= []).add(r);
    }
    Object? next(String m) {
      final q = queue[m];
      if (q == null || q.isEmpty) return null;
      return q.length == 1 ? q.first : q.removeAt(0);
    }

    final t = FakeTransport(autoReply: (m, p) => next(m));
    final c = EngineClient(() async => t, backoff: const [Duration(milliseconds: 1)])..start();
    await pumpEventQueue();
    expect(c.link.value, Link.connected);
    expect(c.served, containsAll(['status_full', 'pick_folder', 'set_settings', 'to_main', 'ui_hidden']));
    expect(c.enginePid, 4242);
    expect(t.sent.firstWhere((m) => m['method'] == 'ui_shown')['params'], {'window': 'main'});

    final a = await c.search('tax pdf');
    expect(a.results.single.path, r'C:\Users\me\Documents\tax 2025.pdf');
    expect(a.understood, ['pdf']);
    expect((await c.open(7)).ok, isTrue);
    expect(await c.pathOf(7), r'C:\Users\me\Documents\tax 2025.pdf');
    expect(await c.hereFolder(), r'C:\Users\me\Downloads');
    expect((await c.statusFull()).details!.plan!.cpu, 16);
    expect((await c.learnedApps()).single.exe, 'game.exe');
    expect((await c.hardware())!.ramGb, 15.7);
    final ch = await c.setSettings({'theme': 'light', 'content_max_mb': 50});
    expect(ch.changed, ['theme', 'content_max_mb']);
    expect(ch.settings.number('content_max_mb'), 50);
    final pick = await c.pickFolder();
    expect(pick.path, r'C:\Users\me\Projects');
    expect(pick.busy, isFalse);
    expect((await c.wsearchState()).running, isTrue);
    expect((await c.downloadModel('meaning')).error, 'Allow the download in Settings first.');
    expect((await c.downloadModel('photo')).error, 'Allow the photo model download in Settings first.');
    await c.search('x' * 2500);
    expect(((t.sent.last['params'] as Map)['text'] as String).length, 2000); // the engine refuses longer
    await c.wipe('DELETE');
    await c.pauseFor(const Duration(hours: 1));
    await c.resetLearned('game.exe');
    await c.toMain('tax pdf');
    await c.uiHidden('main');
    await c.quit();

    Map<String, Object?> params(String m) =>
        (t.sent.lastWhere((x) => x['method'] == m)['params'] as Map).cast<String, Object?>();
    expect(params('set_settings'), {'changes': {'theme': 'light', 'content_max_mb': 50}});
    expect(params('wipe'), {'confirm': 'DELETE'});
    expect(params('quit'), {'confirm': 'QUIT'});
    expect(params('pause_for'), {'seconds': 3600});
    expect(params('reset_learned'), {'exe': 'game.exe'});
    expect(params('to_main'), {'text': 'tax pdf'});
    expect(params('ui_hidden'), {'window': 'main'});
    expect(params('download_model'), isEmpty);

    // quitting: the client stops reconnecting
    t.push({'jsonrpc': '2.0', 'method': 'quitting', 'params': {}});
    await pumpEventQueue();
    expect(c.quitting, isTrue);
    t.drop();
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(c.link.value, Link.offline);
    c.dispose();
  });

  test('watching the Indexing page subscribes to status_full, and stops', () async {
    final t = FakeTransport(autoReply: (m, p) => switch (m) {
          'hello' => {'protocol': 1, 'pid': 1, 'methods': ['hello', 'subscribe', 'unsubscribe', 'status', 'status_full']},
          'subscribe' || 'unsubscribe' => {'events': <String>[]},
          'status' => {'level': 'gentle', 'reason': 'r', 'phase': 'text', 'files': 1, 'paused': ''},
          _ => null,
        });
    final c = EngineClient(() async => t, backoff: const [Duration(milliseconds: 1)])..start();
    await pumpEventQueue();
    unawaited(c.watchDetails(true));
    await pumpEventQueue();
    unawaited(c.watchDetails(false));
    await pumpEventQueue();
    final subs = t.sent.where((m) => m['method'] == 'subscribe' || m['method'] == 'unsubscribe').toList();
    expect(subs.last['method'], 'unsubscribe');
    expect((subs.last['params'] as Map)['events'], ['status_full']);
    expect((subs[1]['params'] as Map)['events'], ['status_full']);
    c.dispose();
  });
}
