/// An in-memory engine with the contract's shapes (apps/find/contract, protocol 1) and a small made-up index. Used
/// by the tests, by `NOBAD_FIND_FAKE_ENGINE=1` (screenshots without an engine), and by [WiredEngine] for whatever
/// an older engine doesn't serve yet.
///
/// With [live] it also does what the engine does on its own: `status` every 2 s, `status_full` every 2 s while
/// watched, and download progress. That's the engine's side; the UI still only listens.
library;

import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';

import 'engine_api.dart';
import 'events.dart';
import 'models/result.dart';
import 'models/settings.dart';
import 'models/status.dart';

class FakeEngine implements EngineApi {
  FakeEngine({
    List<FileResult>? files,
    Link link = Link.connected,
    Map<String, Object?> settings = const {'welcome_seen': true, 'bg_notice_seen': true},
    this.live = false,
    DateTime Function()? clock,
  })  : files = files ?? sampleFiles(),
        _clock = clock ?? (() => DateTime(2026, 11, 19, 14, 30)) {
    _link.value = link;
    _settings = {...Settings.defaults, ...settings};
    _brief = const EngineStatus(level: 'gentle', reason: _gentle, phase: 'text', files: 48210);
    if (live) _ticker = Timer.periodic(const Duration(seconds: 2), (_) => _tick());
  }

  static const _gentle = "Gentle: you're using the PC, so NOBAD Find works with 2 of 16 threads.";

  final List<FileResult> files;
  final bool live;
  final DateTime Function() _clock;
  final _link = ValueNotifier(Link.connected);
  final _events = StreamController<EngineEvent>.broadcast(sync: true);
  late Map<String, Object?> _settings;
  late EngineStatus _brief;
  Timer? _ticker;
  final _downloads = <String, Timer>{};
  final _models = <String, ModelState>{'meaning': const ModelState(), 'photo': const ModelState()};
  var _watching = false;
  var _tickN = 0;

  // What the UI asked for (tests read these).
  final searches = <String>[];
  final searchFilters = <SearchFilters>[];
  final opened = <int>[];
  final revealed = <int>[];
  final thumbsAsked = <int>[];
  final forgotten = <int>[];
  final settingsSet = <Map<String, Object?>>[];
  final calls = <String>[];
  bool openOk = true;
  bool pickBusy = false;
  bool offline = false;
  String here = '';
  String pickAnswer = r'C:\Users\me\Projects';
  List<LearnedApp> learned = [
    const LearnedApp(exe: 'Cyberpunk2077.exe', seen: 6, lagEvents: 2,
        reason: 'Lagged twice in the last 14 days, so NOBAD Find pauses while it runs.'),
    const LearnedApp(exe: 'Resolve.exe', seen: 3, lagEvents: 1,
        reason: 'Lagged once, so NOBAD Find works with 1 worker while it runs.'),
  ];
  WsearchState wsearch = const WsearchState(start: 'delayed-auto', running: true);

  set linkState(Link l) => _link.value = l;
  bool get watching => _watching;

  void emit(EngineEvent e) {
    if (e is StatusEvent) _brief = e.status;
    if (!_events.isClosed) _events.add(e);
  }

  @override
  ValueListenable<Link> get link => _link;
  @override
  Stream<EngineEvent> get events => _events.stream;
  @override
  EngineStatus? get lastStatus => _brief;

  Future<T> _answer<T>(String name, T Function() f) async {
    calls.add(name);
    if (offline) throw const EngineOffline();
    return f();
  }

  static const _ok = ActionResult(true);

  // ---------- search and results ----------
  @override
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none}) => _answer('search', () {
        searches.add(text);
        searchFilters.add(filters);
        final t = text.trim().toLowerCase();
        if (t.isEmpty && !filters.narrows && filters.sort.isEmpty) return SearchAnswer.empty;
        var rows = files.where((f) {
          if (filters.kind.isNotEmpty && f.kind != filters.kind) return false;
          if (filters.folder.isNotEmpty && !f.dir.toLowerCase().startsWith(filters.folder.toLowerCase())) {
            return false;
          }
          if (t.isEmpty) return true;
          final words = t.split(RegExp(r'\s+')).where((w) => !_stop.contains(w));
          final hay = '${f.name} ${f.kind} ${f.dir}'.toLowerCase();
          return words.isNotEmpty && words.every(hay.contains);
        }).toList();
        if (filters.sort == 'newest') rows.sort((a, b) => (b.mtime ?? 0).compareTo(a.mtime ?? 0));
        if (filters.sort == 'name') rows.sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
        if (filters.sort == 'largest') rows.sort((a, b) => (b.size ?? 0).compareTo(a.size ?? 0));
        if (t.isEmpty) rows = [for (final r in rows) if (!r.weak) r];
        return SearchAnswer(
          results: rows,
          ms: 4,
          understood: [
            if (t.contains('pdf')) 'pdf',
            if (t.contains('last week')) 'changed in the last 7 days',
            if (t.contains('photo')) 'photos',
          ],
        );
      });

  static const _stop = {'from', 'in', 'my', 'the', 'last', 'week', 'photos', 'photo', 'pdf'};

  @override
  Future<ActionResult> open(int id) => _answer('open', () {
        opened.add(id);
        return openOk ? _ok : const ActionResult(false, "That file isn't there any more.");
      });

  @override
  Future<ActionResult> reveal(int id) => _answer('reveal', () {
        revealed.add(id);
        return _ok;
      });

  @override
  Future<Uint8List?> thumbnail(int id) async {
    thumbsAsked.add(id);
    if (!live) return null;
    final f = _file(id);
    return f == null || f.kind != 'image' ? null : _picture(id);
  }

  FileResult? _file(int id) => files.where((x) => x.id == id).firstOrNull;

  @override
  Future<String> pathOf(int id) => _answer('path_of', () {
        final f = _file(id);
        return f == null ? '' : (f.path.isNotEmpty ? f.path : '${f.dir}\\${f.name}');
      });

  @override
  Future<ActionResult> forget(int id) => _answer('forget', () {
        final f = _file(id);
        if (f == null) return const ActionResult(false);
        forgotten.add(id);
        files.remove(f);
        _settings['exclude'] = [...Settings(_settings).list('exclude'), '${f.dir}\\${f.name}'];
        return _ok;
      });

  @override
  Future<String> hereFolder() => _answer('here_folder', () => here);

  @override
  Future<void> toMain(String text) => _answer('to_main', () => emit(ShowEvent('main', text: text)));

  // ---------- status ----------
  @override
  Future<EngineStatus> status() => _answer('status', () => _brief);

  @override
  Future<EngineStatus> statusFull() => _answer('status_full', _full);

  @override
  Future<void> watchDetails(bool on) => _answer('watch_details', () => _watching = on);

  @override
  Future<ActionResult> pauseFor(Duration d) => _answer('pause_for', () {
        _level('paused', 'Paused: you paused NOBAD Find for ${d.inMinutes} min');
        return _ok;
      });

  @override
  Future<ActionResult> resume() => _answer('resume', () {
        _level('gentle', _gentle);
        return _ok;
      });

  void _level(String level, String reason) {
    _brief = EngineStatus(level: level, reason: reason, phase: _brief.phase, files: _brief.files,
        paused: level == 'paused' ? 'for 1 hour' : '');
    emit(LevelEvent(level, reason));
    emit(ActivityEvent(ActivityEntry(t: _now(), kind: 'level', text: reason)));
    emit(StatusEvent(_brief));
    if (_watching) emit(StatusFullEvent(_full()));
  }

  @override
  Future<List<LearnedApp>> learnedApps() => _answer('learned_apps', () => List.of(learned));

  @override
  Future<ActionResult> resetLearned([String? exe]) => _answer('reset_learned', () {
        learned = exe == null ? [] : [for (final a in learned) if (a.exe != exe) a];
        return _ok;
      });

  @override
  Future<Hardware?> hardware() => _answer('hardware', () => const Hardware(ramGb: 15.7, cores: 12, threads: 16,
      avx2: true, gpu: 'Intel(R) Iris(R) Xe Graphics', vramGb: 0.1, diskFreeGb: 211.4, ssd: true));

  // ---------- settings ----------
  @override
  Future<Settings> getSettings() => _answer('get_settings', () => Settings(Map.of(_settings)));

  /// Like settings.coerce: a value that doesn't fit becomes the default; unknown names and wsearch_prev are ignored.
  @override
  Future<SettingsChange> setSettings(Map<String, Object?> changes) => _answer('set_settings', () {
        settingsSet.add(changes);
        final changed = <String>[];
        for (final e in changes.entries) {
          if (e.key == 'wsearch_prev' || !Settings.defaults.containsKey(e.key)) continue;
          final want = Settings.defaults[e.key];
          final fits = switch (want) {
            bool _ => e.value is bool,
            int _ => e.value is int && (e.value as int) >= 0,
            String _ => e.value is String,
            List _ => e.value is List && (e.value as List).every((x) => x is String),
            _ => false,
          };
          final v = fits ? e.value : want;
          if (!_same(_settings[e.key], v)) {
            _settings[e.key] = v;
            changed.add(e.key);
          }
        }
        return SettingsChange(changed, Settings(Map.of(_settings)));
      });

  static bool _same(Object? a, Object? b) => a is List && b is List ? listEquals(a, b) : a == b;

  @override
  Future<FolderPick> pickFolder() => _answer('pick_folder', () => FolderPick(pickAnswer, busy: pickBusy));

  @override
  Future<ActionResult> rescan() => _answer('rescan', () => _ok);

  @override
  Future<ActionResult> wipe(String confirm) =>
      _answer('wipe', () => confirm == 'DELETE' ? _ok : const ActionResult(false));

  // ---------- models ----------
  @override
  Future<ActionResult> downloadModel(String model) => _answer('download_$model', () {
        final allow = model == 'photo' ? 'allow_photo_model_download' : 'allow_model_download';
        if (_settings[allow] != true) {
          return ActionResult(false, model == 'photo'
              ? 'Allow the photo model download in Settings first.'
              : 'Allow the download in Settings first.');
        }
        if (_models[model]!.downloading) return _ok;
        final size = model == 'photo' ? 211.0 : 23.0;
        var got = 0.0;
        void push(String state, double mbS) {
          _models[model] = ModelState(state: state, got: (got * 1048576).round(), size: (size * 1048576).round());
          emit(DownloadEvent(id: model, state: state, gotMb: got, sizeMb: size, mbS: mbS));
        }

        push('downloading', 0);
        if (live) {
          _downloads[model]?.cancel();
          _downloads[model] = Timer.periodic(const Duration(milliseconds: 500), (t) {
            got = (got + size / 14).clamp(0, size).toDouble();
            final done = got >= size;
            push(done ? 'ready' : 'downloading', done ? 0 : 4.2);
            if (done) {
              t.cancel();
              _settings[model == 'photo' ? 'photo_meaning' : 'semantic'] = true;
            }
          });
        }
        return _ok;
      });

  // ---------- Windows Search ----------
  @override
  Future<WsearchState> wsearchState() => _answer('wsearch_state', () => wsearch);

  @override
  Future<ActionResult> useInsteadOfWindowsSearch(bool on) => _answer('use_instead_of_windows_search', () {
        wsearch = WsearchState(start: on ? 'disabled' : 'delayed-auto', running: !on,
            saved: on ? 'delayed-auto' : '');
        if (on) _settings['autostart'] = true;
        return _ok;
      });

  // ---------- the window ----------
  @override
  Future<void> uiShown(String window) => _answer('ui_shown', () {});
  @override
  Future<void> uiHidden(String window) => _answer('ui_hidden', () {});

  @override
  Future<ActionResult> quit() => _answer('quit', () {
        emit(const QuittingEvent());
        return _ok;
      });

  @override
  void dispose() {
    _ticker?.cancel();
    for (final t in _downloads.values) {
      t.cancel();
    }
    _events.close();
  }

  // ---------- the made-up index ----------
  double _now() => _clock().millisecondsSinceEpoch / 1000;

  void _tick() {
    _tickN++;
    emit(StatusEvent(_brief));
    if (_watching) emit(StatusFullEvent(_full()));
  }

  EngineStatus _full() {
    final now = _now();
    final shift = _tickN;
    final history = [
      for (var i = 0; i < 150; i++)
        HistoryPoint(t: now - (149 - i) * 2, findCpu: _cpuAt(i + shift),
            findMb: 410 + 60 * _wave(i + shift, 37) + (i + shift > 95 ? 90.0 : 0)),
    ];
    final meaning = _models['meaning']!, photoM = _models['photo']!;
    return EngineStatus(
      level: _brief.level,
      reason: _brief.reason,
      phase: _brief.phase,
      files: _brief.files,
      paused: _brief.paused,
      details: IndexDetails(
        version: '0.8.0',
        withText: 31877,
        memoryMb: 186,
        rate: 2140,
        dbBytes: 214 * 1048576,
        plan: const WorkPlan(cpu: 16, textWorkers: 2, textWorkersIdle: 6, ssd: true),
        speed: "gentle (you're using the PC)",
        ocrOn: true,
        roots: const [r'C:\Users\me', r'D:\'],
        drives: const [
          Drive(root: r'C:\', label: 'Windows', type: 'fixed'),
          Drive(root: r'D:\', label: 'Data', type: 'fixed'),
          Drive(root: r'E:\', label: 'SANDISK', type: 'removable', present: false),
        ],
        encrypted: true,
        model: meaning,
        photoModel: photoM,
        history: history,
        resources: Resources(
          cpu: history.last.findCpu,
          memoryMb: history.last.findMb,
          readMbS: 3.4,
          processes: [
            const ProcessUse(name: 'Main', pid: 11240, cpu: 1.2, memoryMb: 186),
            ProcessUse(name: 'Text reader', pid: 15012, cpu: history.last.findCpu * .6, memoryMb: 142),
            ProcessUse(name: 'Text reader', pid: 15876, cpu: history.last.findCpu * .4, memoryMb: 131),
          ],
        ),
        phases: [
          const PhaseRow(id: 'names', label: 'Finding file names', state: PhaseState.done, done: 48210),
          PhaseRow(id: 'text', label: 'Reading documents', state: PhaseState.running, done: 31877 + shift * 29,
              total: 40112, rate: 14.6, etaS: 564 - shift * 2),
          const PhaseRow(id: 'ocr', label: 'Reading words in pictures', state: PhaseState.waiting, done: 120,
              total: 2304),
          PhaseRow(id: 'meaning', label: 'Learning what files mean',
              state: meaning.ready ? PhaseState.waiting : PhaseState.off),
          PhaseRow(id: 'photos', label: 'Looking at photos', state: photoM.ready ? PhaseState.waiting : PhaseState.off),
          const PhaseRow(id: 'watching', label: 'Watching for changes', state: PhaseState.waiting),
        ],
        models: [
          _card('meaning', 'Meaning search (all-MiniLM-L6-v2)', 23, meaning),
          _card('photo', 'Photo search (SigLIP base)', 211, photoM),
          const ModelCard(id: 'ocr', name: 'Windows OCR', license: 'Windows', onDisk: true, device: 'Windows',
              items: 120),
        ],
        activity: [
          ActivityEntry(t: now - 60, kind: 'level', text: _gentle),
          ActivityEntry(t: now - 840, kind: 'info', text: 'Finished finding file names: 48,210 files and folders.'),
          ActivityEntry(t: now - 1500, kind: 'level',
              text: 'Paused: Cyberpunk2077 is running and lagged before, so NOBAD Find waits until it closes.'),
          ActivityEntry(t: now - 2700, kind: 'level', text: "Full speed: you're away from the PC."),
        ],
      ),
    );
  }

  static ModelCard _card(String id, String name, double size, ModelState m) => ModelCard(
      id: id, name: name, license: 'Apache-2.0', sizeMb: size, onDisk: m.ready, device: 'CPU',
      download: m.downloading ? DownloadProgress(gotMb: m.got / 1048576, sizeMb: m.size / 1048576, mbS: 4.2) : null);

  static double _wave(int i, int period) {
    final x = (i % period) / period;
    return x < .5 ? x * 2 : (1 - x) * 2;
  }

  static double _cpuAt(int i) {
    final base = 3 + 5 * _wave(i, 23) + 3 * _wave(i, 7);
    return i % 50 > 40 ? base + 9 : base;
  }

  /// A preview for a made-up photo: a soft two-colour gradient (only with [live], for screenshots).
  static Future<Uint8List?> _picture(int id) async {
    final rec = ui.PictureRecorder();
    final c = ui.Canvas(rec);
    const palettes = [
      [ui.Color(0xFF1B3A5C), ui.Color(0xFFE9B872)],
      [ui.Color(0xFF2E4B3C), ui.Color(0xFFB8D4C8)],
      [ui.Color(0xFF5B2A3A), ui.Color(0xFFF2A07B)],
    ];
    final p = palettes[id % palettes.length];
    c.drawRect(const ui.Rect.fromLTWH(0, 0, 96, 96),
        ui.Paint()..shader = ui.Gradient.linear(const ui.Offset(0, 0), const ui.Offset(0, 96), p));
    c.drawCircle(const ui.Offset(68, 30), 12, ui.Paint()..color = const ui.Color(0xCCFFF4D6));
    final img = await rec.endRecording().toImage(96, 96);
    final data = await img.toByteData(format: ui.ImageByteFormat.png);
    img.dispose();
    return data?.buffer.asUint8List();
  }
}

/// The made-up index: a few files of every kind, with folders and ages that read like a real profile.
List<FileResult> sampleFiles() => [
      const FileResult(id: 1, name: 'tax return 2025.pdf', dir: r'C:\Users\me\Documents\Taxes', kind: 'pdf',
          size: 482113, ago: '3 days ago', mtime: 1763200000, why: ['name matches'],
          snippet: 'your \x02tax\x03 refund for 2025 is expected within six weeks of filing'),
      const FileResult(id: 2, name: 'tax notes.txt', dir: r'C:\Users\me\Desktop', kind: 'text', size: 912,
          ago: '1 h ago', mtime: 1763500000, why: ['name matches']),
      const FileResult(id: 3, name: 'beach.jpg', dir: r'C:\Users\me\Pictures\2026\March', kind: 'image',
          size: 3400000, ago: 'March', mtime: 1742000000, why: ['the picture may show it']),
      const FileResult(id: 4, name: '<b>tax</b> & "quotes".docx', dir: r'D:\Work', kind: 'document', size: 20000,
          ago: '2 weeks ago', mtime: 1762300000, why: ['text inside matches']),
      const FileResult(id: 5, name: 'old tax scan.pdf', dir: r'C:\Users\me\Scans', kind: 'pdf', size: 1200000,
          ago: 'last year', mtime: 1730000000, weak: true, why: ['text has a loose meaning']),
    ];

/// A bigger made-up index for screenshots (NOBAD_FIND_FAKE_ENGINE).
List<FileResult> demoFiles() => [
      ...sampleFiles(),
      const FileResult(id: 6, name: 'rent agreement 2026.pdf', dir: r'C:\Users\me\Documents\Home', kind: 'pdf',
          size: 228400, ago: 'yesterday', mtime: 1763450000, why: ['name matches', 'changed last week'],
          snippet: 'the monthly \x02rent\x03 of 1,450 is due on the first day of each month'),
      const FileResult(id: 7, name: 'budget 2026.xlsx', dir: r'C:\Users\me\Documents\Money', kind: 'spreadsheet',
          size: 48210, ago: '5 days ago', mtime: 1763100000, why: ['name matches']),
      const FileResult(id: 8, name: 'IMG_0042.jpg', dir: r'C:\Users\me\Pictures\2026\March', kind: 'image',
          size: 4100000, ago: 'March', mtime: 1742100000, why: ['the picture may show it']),
      const FileResult(id: 9, name: 'quarterly review.pptx', dir: r'D:\Work\Reviews', kind: 'slides',
          size: 5600000, ago: '2 weeks ago', mtime: 1762200000, why: ['text inside matches']),
      const FileResult(id: 10, name: 'invoice-march.pdf', dir: r'C:\Users\me\Downloads', kind: 'pdf', size: 88000,
          ago: 'March', mtime: 1742500000, why: ['name matches']),
      const FileResult(id: 11, name: 'trip video.mp4', dir: r'C:\Users\me\Videos', kind: 'video', size: 412000000,
          ago: '4 months ago', mtime: 1752000000, why: ['name matches']),
      const FileResult(id: 12, name: 'notes.md', dir: r'C:\Users\me\Documents', kind: 'text', size: 3200,
          ago: 'today', mtime: 1763520000, why: ['name matches']),
      const FileResult(id: 13, name: 'IMG_0107.jpg', dir: r'C:\Users\me\Pictures\2026\March', kind: 'image',
          size: 3900000, ago: 'March', mtime: 1742200000, why: ['the picture may show it']),
    ];

List<FileResult> manyFiles(int n) => [
      for (var i = 0; i < n; i++)
        FileResult(id: 100 + i, name: 'report $i.pdf', dir: r'C:\Users\me\Reports\Quarterly\Archive', kind: 'pdf'),
    ];
