// The engine contract (apps/vpn/contract), from the window's side: every request the window sends is exactly a
// line of the recorded transcripts (method and params), every answer and event in them is read without an error,
// and the window's calls stay inside the method schema the engine enforces.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_vpn_ui/engine/engine.dart';
import 'package:nobad_vpn_ui/engine/models.dart';
import 'package:nobad_vpn_ui/engine/rpc.dart' show mainEvents, miniEvents;
import 'package:nobad_vpn_ui/state/vpn_controller.dart';

const contract = '../contract';

List<Map<String, Object?>> transcript(String name) => [
  for (final l in File('$contract/transcripts/$name').readAsLinesSync())
    if (l.trim().isNotEmpty) jsonDecode(l) as Map<String, Object?>,
];

Map<String, Object?> sendOf(Map<String, Object?> item) => item['send'] as Map<String, Object?>;

/// Records what the typed calls send.
class Recorder implements EngineApi {
  final sent = <(String, Map<String, Object?>)>[];
  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) async {
    sent.add((method, params));
    return {'ok': true};
  }

  @override
  ValueListenable<Link> get link => ValueNotifier(Link.connected);
  @override
  Stream<EngineEvent> get events => const Stream.empty();
  @override
  Future<void> shown(bool on) async {}
  @override
  String get engineVersion => '';
  @override
  void dispose() {}
}

void main() {
  final schema = jsonDecode(File('$contract/methods.schema.json').readAsStringSync()) as Map<String, Object?>;
  final methods = (schema['methods'] as Map).cast<String, Map<String, Object?>>();
  final events = jsonDecode(File('$contract/events.schema.json').readAsStringSync()) as Map<String, Object?>;

  test('protocol 1 on both sides', () {
    expect(schema['protocol'], 1);
    expect(events['protocol'], 1);
  });

  test('the typed calls send exactly what the transcripts recorded', () async {
    final r = Recorder();
    final calls = <String, Future<Object?> Function()>{
      '02:1': () => r.connect('JP-FREE-3'),
      '02:4': () => r.favorite('JP-FREE-3'),
      '02:5': () => r.setSetting('kill_switch', true),
      '02:7': () => r.setSetting('fallback_dns', '1.1.1.1, not-an-ip'),
      '02:9': r.disconnect,
      '03:1': () => r.openUrl('proton_signup'),
      '03:3': r.freeScan,
      '03:4': () => r.freeImport(['wg-JP-FREE-3.conf']),
      '03:6': r.wizardDone,
      '04:2': () => r.uiShow('mini'),
    };
    final files = {'02': '02-connect-and-settings.jsonl', '03': '03-free-servers.jsonl', '04': '04-events.jsonl'};
    for (final MapEntry(key: k, value: f) in calls.entries) {
      final [file, id] = k.split(':');
      final line = transcript(files[file]!).firstWhere((x) => x.containsKey('send') && sendOf(x)['id'] == int.parse(id));
      r.sent.clear();
      await f();
      expect(r.sent.single.$1, sendOf(line)['method'], reason: k);
      expect(r.sent.single.$2, sendOf(line)['params'], reason: k);
    }
  });

  test('every answer and event in the transcripts reads without an error', () {
    for (final f in Directory('$contract/transcripts').listSync().whereType<File>()) {
      for (final l in f.readAsLinesSync().where((l) => l.trim().isNotEmpty)) {
        final m = jsonDecode(l) as Map<String, Object?>;
        final recv = m['recv'];
        if (recv is! Map) continue;
        if (recv['method'] == 'state' || (recv['result'] is Map && (recv['result'] as Map).containsKey('regions'))) {
          final s = VpnState.fromJson(recv['params'] ?? recv['result']);
          expect(s.regions, isNotEmpty);
          expect(s.protection, Protection.off);
        } else if (recv['method'] == 'error_action') {
          final e = EngineError.fromJson(recv['params'])!;
          expect(e.actions.map((a) => a.id), ['retry', 'check_endpoint']);
        } else if (recv['method'] == 'traffic') {
          expect(Traffic.fromJson(recv['params']).rxBps, greaterThan(0));
        } else if (recv['result'] is Map && (recv['result'] as Map).containsKey('ok')) {
          final a = Answer.fromJson(recv['result']);
          if (!a.ok) expect(a.error, isNotEmpty, reason: 'never a bare {"ok": false}: $l');
        }
      }
    }
  });

  test('the controller takes every recorded event', () async {
    final events = <EngineEvent>[];
    for (final name in ['01-start-up.jsonl', '04-events.jsonl']) {
      for (final m in transcript(name)) {
        final recv = m['recv'];
        if (recv is Map && recv['method'] is String) events.add(EngineEvent(recv['method'] as String, recv['params']));
        if (recv is Map && recv['result'] is Map && (recv['result'] as Map).containsKey('regions')) {
          events.add(EngineEvent('state', recv['result']));
        }
      }
    }
    final e = _Replay(events);
    final vpn = VpnController(e);
    await pumpEventQueue();
    expect(vpn.state!.regions.length, 2);
    expect(vpn.state!.error!.code, 'handshake');
    expect(vpn.samples.rx.single, 4200000.5);
    vpn.dispose();
  });

  test('the window subscribes only to events the engine has, and calls only methods in the schema', () {
    final known = {...(events['events'] as Map).keys};
    final engineEvents = File('../nobadvpn/rpc/events.py').readAsStringSync();
    for (final e in {...mainEvents, ...miniEvents}) {
      expect(engineEvents.contains('"$e"'), isTrue, reason: e);
    }
    expect(known, contains('state'));
    final used = RegExp(r"_ok\('([a-z_]+)'").allMatches(File('lib/engine/engine.dart').readAsStringSync()).map((m) => m[1]!);
    for (final m in used) {
      expect(methods.containsKey(m), isTrue, reason: m);
    }
    for (final m in ['state', 'net_changes', 'hello', 'subscribe', 'ui_shown', 'ui_hidden']) {
      expect(methods.containsKey(m), isTrue, reason: m);
    }
  });

  test('parameters the window sends fit the schema (names are config names, never paths)', () {
    final name = (methods['connect']!['properties'] as Map)['name'] as Map;
    final re = RegExp(name['pattern'] as String);
    expect(re.hasMatch('JP-FREE-3'), isTrue);
    expect(re.hasMatch(r'..\..\Windows'), isFalse);
    final files = ((methods['free_import']!['properties'] as Map)['files'] as Map)['items'] as Map;
    expect(RegExp(files['pattern'] as String).hasMatch(r'C:\x.conf'), isFalse);
  });
}

class _Replay implements EngineApi {
  _Replay(this._events);
  final List<EngineEvent> _events;
  @override
  ValueListenable<Link> get link => ValueNotifier(Link.offline);
  @override
  Stream<EngineEvent> get events => Stream.fromIterable(_events);
  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) async => throw const EngineOffline();
  @override
  Future<void> shown(bool on) async {}
  @override
  String get engineVersion => '';
  @override
  void dispose() {}
}
