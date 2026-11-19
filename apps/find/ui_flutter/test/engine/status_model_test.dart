import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/format.dart';
import 'package:nobad_find/engine/models/status.dart';

void main() {
  group('words and numbers, the same as the 0.7.0 page', () {
    test('groupDigits', () {
      expect(groupDigits(0), '0');
      expect(groupDigits(999), '999');
      expect(groupDigits(12345), '12,345');
      expect(groupDigits(1234567), '1,234,567');
    });

    test('mb', () {
      expect(mb(3.24), '3.2 MB');
      expect(mb(42), '42 MB');
      expect(mb(512.4), '512 MB');
      expect(mb(2048), '2.0 GB');
      expect(mb(double.nan), '0.0 MB');
    });

    test('span', () {
      expect(span(10), 'under a minute');
      expect(span(600), 'about 10 min');
      expect(span(7200), 'about 2 h');
      expect(span(3 * 86400), 'about 3 days');
    });

    test('perTime', () {
      expect(perTime(0, 'files'), '');
      expect(perTime(12.4, 'files'), '12 files per second');
      expect(perTime(2.26, 'files'), '2.3 files per second');
      expect(perTime(0.1, 'files'), '6 files per minute');
    });

    test('pct', () {
      expect(pct(null), '–');
      expect(pct(12.6), '13%');
    });
  });

  group('status', () {
    test('the brief status the prototype engine sends', () {
      final s = EngineStatus.fromJson(
          {'level': 'gentle', 'reason': 'r', 'phase': 'text', 'files': 12, 'paused': ''});
      expect(s.levelLabel, 'Working gently');
      expect(s.phaseLabel, 'Reading text');
      expect(s.details, isNull);
    });

    test('paused shows why', () {
      expect(const EngineStatus(phase: 'text', paused: 'on battery').phaseLabel, 'Paused · on battery');
    });

    test('the full status (api.status) fills the details, odd values become safe defaults', () {
      final s = EngineStatus.fromJson({
        'level': 'full', 'reason': 'Away', 'phase': 'watching', 'files': 48210, 'with_text': 9000,
        'vectors': 100, 'name_vectors': 20, 'photo_vectors': 7, 'encrypted': true, 'db_bytes': 10485760,
        'version': '0.7.0', 'roots': [r'C:\Users\me', 3], 'ocr': 'Windows OCR is missing',
        'drives': [{'root': r'E:\', 'label': 'USB', 'type': 'removable', 'present': false}, 'junk'],
        'plan': {'cpu': 16, 'text_workers': 4, 'text_workers_idle': 6, 'ssd': true},
        'speed': "gentle (you're using the PC)",
        'resources': {'cpu': 3.5, 'memory_mb': 300, 'read_mb_s': 1.25, 'gpu': null,
          'processes': [{'name': 'Main', 'pid': 1, 'cpu': 1.0, 'memory_mb': 120}]},
        'history': [{'t': 1.0, 'find_cpu': 2.0, 'find_mb': 300}, {'t': 'x'}],
        'phases': [{'id': 'names', 'label': 'Finding file names', 'state': 'done', 'done': 5, 'total': null,
          'rate': 0, 'eta_s': null}],
        'models': [{'id': 'meaning', 'name': 'Meaning search (all-MiniLM-L6-v2)', 'license': 'Apache-2.0',
          'size_mb': 23, 'on_disk': true, 'loaded': false, 'memory_mb': null, 'device': 'CPU', 'items': 120,
          'download': null}],
        'activity': [{'t': 1700000000.0, 'kind': 'level', 'text': 'Gentle: you are using the PC'}],
        'model': {'state': 'downloading', 'got': 50, 'size': 100, 'error': ''},
        'memory_mb': double.nan,
      });
      final d = s.details!;
      expect(d.encrypted, isTrue);
      expect(d.roots, [r'C:\Users\me']);
      expect(d.drives.single.typeLabel, 'USB / external');
      expect(d.drives.single.present, isFalse);
      expect(d.ocrOn, isFalse);
      expect(d.ocrWhy, 'Windows OCR is missing');
      expect(d.plan!.cpu, 16);
      expect(d.speedLabel, 'gentle');
      expect(d.speedHelp, "Speed: you're using the PC");
      expect(d.resources.processes.single.name, 'Main');
      expect(d.resources.gpu, isNull);
      expect(d.history.length, 2);
      expect(d.history.last.findCpu, 0);
      expect(d.phases.single.state, PhaseState.done);
      expect(d.models.single.stateLine, 'Ready, loads when needed');
      expect(d.activity.single.text, 'Gentle: you are using the PC');
      expect(d.model.state, 'downloading');
      expect(d.model.percent, 50);
      expect(d.memoryMb, isNull);
    });

    test('a model card says what the model is doing', () {
      ModelCard card(Map<String, Object?> m) => ModelCard.fromJson({'name': 'x', ...m})!;
      expect(card({'loaded': true, 'device': 'GPU'}).stateLine, 'In use now on GPU');
      expect(card({'on_disk': false}).stateLine, 'Not downloaded');
      expect(card({'download': {'got_mb': 5, 'size_mb': 23, 'mb_s': 1.5}}).stateLine,
          'Downloading 5.0 MB of 23 MB at 1.5 MB/s');
      expect(card({'size_mb': 23, 'license': 'Apache-2.0', 'items': 1200}).facts,
          '23 MB download · Apache-2.0 · 1,200 items made');
      expect(card({'size_mb': 0, 'license': 'Windows'}).facts, 'Built into Windows · Windows');
    });

    test('a pipeline row: count and the extra line', () {
      final p = PhaseRow.fromJson(
          {'id': 'text', 'label': 'Reading documents', 'state': 'running', 'done': 50, 'total': 200, 'rate': 2.0,
            'eta_s': 75})!;
      expect(p.fraction, .25);
      expect(p.count, '50 / 200');
      expect(p.extra, '2.0 files per second · done in about 1 min');
      expect(p.stateLabel, 'Working');
      final off = PhaseRow.fromJson({'id': 'photos', 'label': 'Looking at photos', 'state': 'off', 'done': 0})!;
      expect(off.count, '');
      expect(off.stateLabel, 'Off');
    });
  });
}
