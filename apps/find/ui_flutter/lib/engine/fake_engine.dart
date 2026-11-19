/// An in-memory engine with the contract's shapes (apps/find/contract, protocol 1) and a small made-up index. Used
/// only by the tests, the goldens and the explicit `NOBAD_FIND_FAKE_ENGINE=1` demo; the app never falls back to it.
///
/// With [live] it also does what the engine does on its own: `status` every 2 s, `status_full` every 2 s while
/// watched, and download progress. That's the engine's side; the UI still only listens.
library;

import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';

import 'engine_api.dart';
import 'events.dart';
import 'models/json.dart';
import 'models/models_info.dart';
import 'models/scope_info.dart';
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
  }) : files = files ?? sampleFiles(),
       _clock = clock ?? (() => DateTime(2026, 11, 19, 14, 30)) {
    _link.value = link;
    _settings = {...Settings.defaults, ...scopeDefaults, ...settings};
    _brief = const EngineStatus(level: 'gentle', reason: _gentle, phase: 'text', files: 48210);
    if (live) _ticker = Timer.periodic(const Duration(seconds: 2), (_) => _tick());
  }

  /// The find-turbo-index settings (an engine with `scope_info`); `turbo` is read-only (turbo_set changes it).
  static const scopeDefaults = <String, Object?>{
    'scope': 'my_files',
    'include_system': false,
    'include_caches': false,
    'include_secrets': false,
  };

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

  /// The next set_settings fails with this (tests).
  RpcException? failNext;

  /// wipe answers ok: false with this sentence (tests).
  String wipeError = '';
  String here = '';
  String pickAnswer = r'C:\Users\me\Projects';
  List<LearnedApp> learned = [
    const LearnedApp(
      exe: 'Cyberpunk2077.exe',
      seen: 6,
      lagEvents: 2,
      reason: 'Lagged twice in the last 14 days, so NOBAD Find pauses while it runs.',
    ),
    const LearnedApp(
      exe: 'Resolve.exe',
      seen: 3,
      lagEvents: 1,
      reason: 'Lagged once, so NOBAD Find works with 1 worker while it runs.',
    ),
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
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none, String channel = 'main'}) =>
      _answer('search', () {
        searches.add(text);
        channels.add(channel);
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
        if (t.isEmpty) rows = rows.where((r) => !r.weak).toList();
        return SearchAnswer(
          results: rows,
          ms: 4,
          understood: [
            if (t.contains('pdf')) 'pdf',
            if (t.contains('last week')) 'changed in the last 7 days',
            if (t.contains('photo')) 'photos',
          ],
          terms: [
            for (final w in t.split(RegExp(r'\s+')))
              if (w.isNotEmpty && !_stop.contains(w)) w,
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
    _brief = EngineStatus(
      level: level,
      reason: reason,
      phase: _brief.phase,
      files: _brief.files,
      paused: level == 'paused' ? 'for 1 hour' : '',
    );
    emit(LevelEvent(level, reason));
    emit(ActivityEvent(ActivityEntry(t: _now(), kind: 'level', text: reason)));
    emit(StatusEvent(_brief));
    if (_watching) emit(StatusFullEvent(_full()));
  }

  @override
  Future<List<LearnedApp>> learnedApps() => _answer('learned_apps', () => List.of(learned));

  @override
  Future<ActionResult> resetLearned([String? exe]) => _answer('reset_learned', () {
    learned = exe == null
        ? []
        : [
            for (final a in learned)
              if (a.exe != exe) a,
          ];
    return _ok;
  });

  @override
  Future<Hardware?> hardware() => _answer(
    'hardware',
    () => const Hardware(
      ramGb: 15.7,
      cores: 12,
      threads: 16,
      avx2: true,
      gpu: 'Intel(R) Iris(R) Xe Graphics',
      vramGb: 0.1,
      diskFreeGb: 211.4,
      ssd: true,
    ),
  );

  // ---------- settings ----------
  @override
  Future<Settings> getSettings() => _answer('get_settings', () => Settings(Map.of(_settings)));

  /// Like settings.coerce: a value that doesn't fit becomes the default; unknown names and wsearch_prev are ignored.
  @override
  Future<SettingsChange> setSettings(Map<String, Object?> changes) => _answer('set_settings', () {
    final fail = failNext;
    if (fail != null) {
      failNext = null;
      throw fail;
    }
    settingsSet.add(changes);
    final changed = <String>[];
    for (final e in changes.entries) {
      final known = {...Settings.defaults, ...scopeDefaults};
      if (e.key == 'wsearch_prev' || !known.containsKey(e.key)) continue;
      final want = known[e.key];
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
  Future<ActionResult> wipe(String confirm) => _answer(
    'wipe',
    () => wipeError.isNotEmpty
        ? ActionResult(false, wipeError)
        : confirm == 'DELETE'
        ? _ok
        : const ActionResult(false),
  );

  // ---------- models ----------
  @override
  Future<ActionResult> downloadModel(String model) => _answer('download_$model', () {
    final allow = model == 'photo' ? 'allow_photo_model_download' : 'allow_model_download';
    if (_settings[allow] != true) {
      return ActionResult(
        false,
        model == 'photo'
            ? 'Allow the photo model download in Settings first.'
            : 'Allow the download in Settings first.',
      );
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
    wsearch = WsearchState(start: on ? 'disabled' : 'delayed-auto', running: !on, saved: on ? 'delayed-auto' : '');
    if (on) _settings['autostart'] = true;
    return _ok;
  });

  // ---------- the window ----------
  @override
  Future<void> uiShown(String window) => _answer('ui_shown', () {});
  @override
  Future<void> uiHidden(String window) => _answer('ui_hidden', () {});

  // ---------- 0.8: models and Open with ----------
  final openedWith = <int>[];

  /// The `channel` of every search, in order.
  final channels = <String>[];
  late ModelsInfo modelsInfo = demoModels();

  /// Answer the 0.8 methods like an older engine: -32601 (tests of the "needs a newer engine" path).
  bool old = false;

  Future<T> _new<T>(String name, T Function() f) => old
      ? Future.error(
          const RpcException(-32601, "This version of NOBAD Find's engine can't do that yet. Update NOBAD Find."),
        )
      : _answer(name, f);

  @override
  Future<ModelsInfo> models() => _new('models', () => modelsInfo);

  /// Settings → Models' language choice (`model_language`): only the recommendation changes.
  @override
  Future<ActionResult> modelLanguage(String focus) => _new('model_language', () {
    final f = LanguageFocus.parse(focus);
    if (f == null) return const ActionResult(false, 'Choose English, many languages or Hindi.');
    modelsInfo = demoModels(focus: f, from: modelsInfo);
    emit(ModelsEvent(modelsInfo));
    return _ok;
  });

  /// A text model was switched: the meaning vectors are rebuilt (status_full gets a "rebuild" phase).
  bool rebuilding = false;

  @override
  Future<ModelUse> modelUse(String feature, String id) => _new('model_use', () {
    final m = modelsInfo.models.where((x) => x.id == id).firstOrNull;
    if (m == null) return const ModelUse(false, error: 'No such model.');
    if (!m.onDisk) return const ModelUse(true, needsDownload: true);
    if (feature == 'text') rebuilding = true;
    _setModels(
      (x) => x.feature == feature
          ? x.withState(
              x.id == id ? ModelUseState.active : (x.state == ModelUseState.active ? ModelUseState.ready : x.state),
            )
          : x,
      tier: 'custom',
    );
    return const ModelUse(true);
  });

  @override
  Future<ActionResult> modelDownload(String id) => _new('model_download', () {
    final m = modelsInfo.models.where((x) => x.id == id).firstOrNull;
    if (m == null) return const ActionResult(false, 'No such model.');
    _setModels((x) => x.id == id ? x.withState(ModelUseState.downloading) : x);
    emit(DownloadEvent(id: id, state: 'downloading', sizeMb: m.sizeMb));
    if (live) {
      Timer(const Duration(seconds: 2), () {
        _setModels((x) => x.id == id ? x.withState(ModelUseState.ready) : x);
        emit(DownloadEvent(id: id, state: 'ready', gotMb: m.sizeMb, sizeMb: m.sizeMb));
      });
    }
    return _ok;
  });

  @override
  Future<ActionResult> modelRemove(String id) => _new('model_remove', () {
    _setModels((x) => x.id == id && !x.builtin ? x.withState(ModelUseState.notDownloaded) : x);
    return _ok;
  });

  @override
  Future<AutoConfig> autoConfigure() => _new('auto_configure', () {
    final steps = [
      for (final m in modelsInfo.models)
        if (m.recommended) AutoStep(feature: m.feature, id: m.id, needsDownload: !m.onDisk),
    ];
    return AutoConfig(tier: modelsInfo.tierRecommended, steps: steps);
  });

  // ---------- what is indexed, and the turbo index ----------
  /// The categories as the engine lists them (nobadfind, find-turbo-index), switched by the settings.
  ScopeInfo get scope {
    final sc = IndexScope.parse(_settings['scope']) ?? IndexScope.myFiles;
    bool on(String k, {bool d = false}) => _settings[k] is bool ? _settings[k] as bool : d;
    return ScopeInfo(
      scope: sc,
      roots: sc == IndexScope.custom
          ? [for (final r in jStrs(_settings['roots'])) r]
          : (sc == IndexScope.wholePc ? const [r'C:\', r'D:\'] : const [r'C:\Users\me']),
      categories: [
        ScopeCategory(
          id: 'system',
          name: 'Windows and programs',
          why: "Windows' own files and installed programs: rarely what you look for, and many of them.",
          examples: const [r'C:\Windows', r'C:\Program Files', r'C:\ProgramData'],
          included: sc == IndexScope.wholePc && on('include_system'),
          locked: sc != IndexScope.wholePc,
          count: sc == IndexScope.wholePc && on('include_system') ? 412880 : 0,
        ),
        ScopeCategory(
          id: 'caches',
          name: 'App data and caches',
          why: 'Settings, temporary files and build folders apps keep for themselves.',
          examples: const [r'C:\Users\me\AppData', r'C:\Users\me\AppData\Local\Temp', r'…\node_modules', r'…\.git'],
          included: on('include_caches'),
          count: on('include_caches') ? 96214 : 0,
        ),
        ScopeCategory(
          id: 'secrets',
          name: 'Keys and password stores',
          why: 'SSH keys, password databases, wallets. Names only if you turn it on; their contents are never read.',
          examples: const [r'C:\Users\me\.ssh', r'…\*.kdbx', r'…\wallet.dat'],
          included: on('include_secrets'),
          count: on('include_secrets') ? 14 : 0,
        ),
        const ScopeCategory(
          id: 'other_profiles',
          name: "Other people's files",
          why: "Other accounts on this PC, recycle bins and System Volume Information: never indexed.",
          examples: [r'C:\Users\guest', r'C:\$Recycle.Bin', r'C:\System Volume Information'],
          locked: true,
        ),
        ScopeCategory(
          id: 'removable',
          name: 'USB and external drives',
          why: 'Indexed while plugged in; their files stay findable, marked "not connected", when you unplug them.',
          examples: const [r'E:\'],
          included: on('index_removable'),
          locked: sc == IndexScope.custom,
          count: on('index_removable') ? 2210 : null,
        ),
        ScopeCategory(
          id: 'network',
          name: 'Network drives',
          why: 'Mapped network drives. Big shares take a while and use your network.',
          examples: const [r'Z:\'],
          included: on('index_network'),
          locked: sc == IndexScope.custom,
        ),
      ],
    );
  }

  late TurboState turbo = const TurboState(
    available: true,
    volumes: [
      TurboVolume(drive: 'C:', ntfs: true, files: 0),
      TurboVolume(drive: 'D:', ntfs: true, files: 0),
      TurboVolume(drive: 'E:', files: 0),
    ],
  );

  /// The answer at Windows' permission prompt (tests: false = "No").
  bool turboPromptYes = true;

  @override
  Future<ScopeInfo> scopeInfo() => _new('scope_info', () => scope);

  @override
  Future<TurboState> turboState() => _new('turbo_state', () => turbo);

  @override
  Future<TurboSet> turboSet(bool on) => _new('turbo_set', () {
    if (on && !turboPromptYes) {
      return TurboSet(false, error: "Windows didn't give permission, so the normal folder walk is used.", state: turbo);
    }
    turbo = TurboState(
      available: true,
      enabled: on,
      running: on,
      volumes: [
        TurboVolume(drive: 'C:', ntfs: true, files: on ? 612408 : 0, usnOk: on, lastScan: on ? 1795500000 : null),
        TurboVolume(drive: 'D:', ntfs: true, files: on ? 88120 : 0, usnOk: on, lastScan: on ? 1795500000 : null),
        const TurboVolume(drive: 'E:', files: 0),
      ],
    );
    _settings['turbo'] = on;
    emit(TurboEvent(turbo));
    return TurboSet(true, state: turbo);
  });

  @override
  Future<ActionResult> openWith(int id) => _new('open_with', () {
    openedWith.add(id);
    return _ok;
  });

  void _setModels(ModelInfo Function(ModelInfo) f, {String? tier}) {
    modelsInfo = ModelsInfo(
      pc: modelsInfo.pc,
      tierRecommended: modelsInfo.tierRecommended,
      tierCurrent: tier ?? modelsInfo.tierCurrent,
      languageFocus: modelsInfo.languageFocus,
      models: [for (final m in modelsInfo.models) f(m)],
    );
    emit(ModelsEvent(modelsInfo));
  }

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
        HistoryPoint(
          t: now - (149 - i) * 2,
          findCpu: _cpuAt(i + shift),
          findMb: 410 + 60 * _wave(i + shift, 37) + (i + shift > 95 ? 90.0 : 0),
        ),
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
          PhaseRow(
            id: 'text',
            label: 'Reading documents',
            state: PhaseState.running,
            done: 31877 + shift * 29,
            total: 40112,
            rate: 14.6,
            etaS: 564 - shift * 2,
          ),
          const PhaseRow(
            id: 'ocr',
            label: 'Reading words in pictures',
            state: PhaseState.waiting,
            done: 120,
            total: 2304,
          ),
          PhaseRow(
            id: 'meaning',
            label: 'Learning what files mean',
            state: meaning.ready ? PhaseState.waiting : PhaseState.off,
          ),
          PhaseRow(id: 'photos', label: 'Looking at photos', state: photoM.ready ? PhaseState.waiting : PhaseState.off),
          if (rebuilding)
            PhaseRow(
              id: 'rebuild',
              label: 'Rebuilding meaning for the new model (the old one works until it is done)',
              state: PhaseState.running,
              done: 9120 + shift * 40,
              total: 48210,
              rate: 38,
              etaS: 1030 - shift * 2,
            ),
          const PhaseRow(id: 'watching', label: 'Watching for changes', state: PhaseState.waiting),
        ],
        models: [
          _card('meaning', 'Meaning search (all-MiniLM-L6-v2)', 23, meaning),
          _card('photo', 'Photo search (SigLIP base)', 211, photoM),
          const ModelCard(
            id: 'ocr',
            name: 'Windows OCR',
            license: 'Windows',
            onDisk: true,
            device: 'Windows',
            items: 120,
          ),
        ],
        activity: [
          ActivityEntry(t: now - 60, kind: 'level', text: _gentle),
          ActivityEntry(t: now - 840, kind: 'info', text: 'Finished finding file names: 48,210 files and folders.'),
          ActivityEntry(
            t: now - 1500,
            kind: 'level',
            text: 'Paused: Cyberpunk2077 is running and lagged before, so NOBAD Find waits until it closes.',
          ),
          ActivityEntry(t: now - 2700, kind: 'level', text: "Full speed: you're away from the PC."),
        ],
      ),
    );
  }

  static ModelCard _card(String id, String name, double size, ModelState m) => ModelCard(
    id: id,
    name: name,
    license: 'Apache-2.0',
    sizeMb: size,
    onDisk: m.ready,
    device: 'CPU',
    download: m.downloading ? DownloadProgress(gotMb: m.got / 1048576, sizeMb: m.size / 1048576, mbS: 4.2) : null,
  );

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
    c.drawRect(
      const ui.Rect.fromLTWH(0, 0, 96, 96),
      ui.Paint()..shader = ui.Gradient.linear(const ui.Offset(0, 0), const ui.Offset(0, 96), p),
    );
    c.drawCircle(const ui.Offset(68, 30), 12, ui.Paint()..color = const ui.Color(0xCCFFF4D6));
    final img = await rec.endRecording().toImage(96, 96);
    final data = await img.toByteData(format: ui.ImageByteFormat.png);
    img.dispose();
    return data?.buffer.asUint8List();
  }
}

/// The made-up index: a few files of every kind, with folders and ages that read like a real profile.
List<FileResult> sampleFiles() => [
  const FileResult(
    id: 1,
    name: 'tax return 2025.pdf',
    dir: r'C:\Users\me\Documents\Taxes',
    kind: 'pdf',
    size: 482113,
    ago: '3 days ago',
    mtime: 1763200000,
    why: ['name matches'],
    snippet: 'your \x02tax\x03 refund for 2025 is expected within six weeks of filing',
  ),
  const FileResult(
    id: 2,
    name: 'tax notes.txt',
    dir: r'C:\Users\me\Desktop',
    kind: 'text',
    size: 912,
    ago: '1 h ago',
    mtime: 1763500000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 3,
    name: 'beach.jpg',
    dir: r'C:\Users\me\Pictures\2026\March',
    kind: 'image',
    size: 3400000,
    ago: 'March',
    mtime: 1742000000,
    why: ['the picture may show it'],
  ),
  const FileResult(
    id: 4,
    name: '<b>tax</b> & "quotes".docx',
    dir: r'D:\Work',
    kind: 'document',
    size: 20000,
    ago: '2 weeks ago',
    mtime: 1762300000,
    why: ['text inside matches'],
  ),
  const FileResult(
    id: 5,
    name: 'old tax scan.pdf',
    dir: r'C:\Users\me\Scans',
    kind: 'pdf',
    size: 1200000,
    ago: 'last year',
    mtime: 1730000000,
    weak: true,
    why: ['text has a loose meaning'],
  ),
];

/// A bigger made-up index for screenshots (NOBAD_FIND_FAKE_ENGINE).
List<FileResult> demoFiles() => [
  ...sampleFiles(),
  const FileResult(
    id: 6,
    name: 'rent agreement 2026.pdf',
    dir: r'C:\Users\me\Documents\Home',
    kind: 'pdf',
    size: 228400,
    ago: 'yesterday',
    mtime: 1763450000,
    why: ['name matches', 'changed last week'],
    snippet: 'the monthly \x02rent\x03 of 1,450 is due on the first day of each month',
  ),
  const FileResult(
    id: 7,
    name: 'budget 2026.xlsx',
    dir: r'C:\Users\me\Documents\Money',
    kind: 'spreadsheet',
    size: 48210,
    ago: '5 days ago',
    mtime: 1763100000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 8,
    name: 'IMG_0042.jpg',
    dir: r'C:\Users\me\Pictures\2026\March',
    kind: 'image',
    size: 4100000,
    ago: 'March',
    mtime: 1742100000,
    why: ['the picture may show it'],
  ),
  const FileResult(
    id: 9,
    name: 'quarterly review.pptx',
    dir: r'D:\Work\Reviews',
    kind: 'slides',
    size: 5600000,
    ago: '2 weeks ago',
    mtime: 1762200000,
    why: ['text inside matches'],
  ),
  const FileResult(
    id: 10,
    name: 'invoice-march.pdf',
    dir: r'C:\Users\me\Downloads',
    kind: 'pdf',
    size: 88000,
    ago: 'March',
    mtime: 1742500000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 11,
    name: 'trip video.mp4',
    dir: r'C:\Users\me\Videos',
    kind: 'video',
    size: 412000000,
    ago: '4 months ago',
    mtime: 1752000000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 12,
    name: 'notes.md',
    dir: r'C:\Users\me\Documents',
    kind: 'text',
    size: 3200,
    ago: 'today',
    mtime: 1763520000,
    why: ['name matches'],
  ),
  const FileResult(
    id: 13,
    name: 'IMG_0107.jpg',
    dir: r'C:\Users\me\Pictures\2026\March',
    kind: 'image',
    size: 3900000,
    ago: 'March',
    mtime: 1742200000,
    why: ['the picture may show it'],
  ),
];

List<FileResult> manyFiles(int n) => [
  for (var i = 0; i < n; i++)
    FileResult(id: 100 + i, name: 'report $i.pdf', dir: r'C:\Users\me\Reports\Quarterly\Archive', kind: 'pdf'),
];

/// The engine's 0.8 catalogue (nobadfind/models.py) as a made-up 6-core laptop would see it: Balanced is
/// recommended, the Best models need more than it has. [focus] picks the recommended text model like the engine's
/// TEXT_CHOICE; [from] keeps the download and use states of an earlier catalogue.
ModelsInfo demoModels({LanguageFocus focus = LanguageFocus.multilingual, ModelsInfo? from}) {
  const best = 'Needs 16 GB of memory and 8 cores (or a graphics card with 4 GB for DirectML)';
  final text = focus == LanguageFocus.english ? 'bge-small-en-v1.5' : 'multilingual-e5-small';
  const hiEn = ['hi', 'en', 'multilingual'];
  const many = ['en', 'hi', 'multilingual (about 100 languages)'];
  final all = <ModelInfo>[
    const ModelInfo(
      id: 'minilm-l6-v2',
      name: 'all-MiniLM-L6-v2',
      tier: 'light',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2',
      sizeMb: 87,
      ramMb: 60,
      speedNote: 'fast: about 40 pieces of text a second on this PC',
      languages: ['en'],
      improves: 'Finds files by what they mean, in English',
      state: ModelUseState.active,
      quality: ModelQuality(recall5: .71, ndcg10: .62),
    ),
    const ModelInfo(
      id: 'bge-small-en-v1.5',
      name: 'BGE small (English) v1.5',
      tier: 'light',
      licence: 'MIT',
      source: 'https://huggingface.co/BAAI/bge-small-en-v1.5 (ONNX: Xenova/bge-small-en-v1.5)',
      sizeMb: 33,
      languages: ['en'],
      quality: ModelQuality(recall5: .78, ndcg10: .69),
    ),
    const ModelInfo(
      id: 'bge-base-en-v1.5',
      name: 'BGE base (English) v1.5',
      tier: 'balanced',
      licence: 'MIT',
      source: 'https://huggingface.co/BAAI/bge-base-en-v1.5 (ONNX: Xenova/bge-base-en-v1.5)',
      sizeMb: 106,
      languages: ['en'],
    ),
    const ModelInfo(
      id: 'multilingual-e5-small',
      name: 'multilingual-e5-small',
      tier: 'balanced',
      licence: 'MIT',
      source: 'https://huggingface.co/intfloat/multilingual-e5-small (ONNX: Xenova/multilingual-e5-small)',
      sizeMb: 129,
      languages: many,
      improves: 'Finds files by meaning in Hindi, mixed Hindi and English, and about 100 other languages',
      quality: ModelQuality(recall5: .80, ndcg10: .70),
    ),
    const ModelInfo(
      id: 'multilingual-e5-base',
      name: 'multilingual-e5-base',
      tier: 'best',
      licence: 'MIT',
      source: 'https://huggingface.co/intfloat/multilingual-e5-base (ONNX: Xenova/multilingual-e5-base)',
      sizeMb: 282,
      languages: many,
      improves: 'The most accurate meaning search, in Hindi, mixed Hindi and English and about 100 languages',
      capable: false,
      capableReason: best,
    ),
    const ModelInfo(
      id: 'paraphrase-multilingual-minilm',
      name: 'paraphrase-multilingual-MiniLM-L12-v2',
      tier: 'balanced',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
      sizeMb: 122,
      languages: hiEn,
    ),
    const ModelInfo(
      id: 'labse',
      name: 'LaBSE',
      tier: 'best',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/sentence-transformers/LaBSE (ONNX: Xenova/LaBSE)',
      sizeMb: 463,
      languages: hiEn,
      capable: false,
      capableReason: best,
    ),
    const ModelInfo(
      id: 'siglip-base',
      feature: 'photo',
      name: 'SigLIP base',
      tier: 'balanced',
      licence: 'Apache-2.0',
      source: 'https://huggingface.co/google/siglip-base-patch16-224 (ONNX: Xenova/siglip-base-patch16-224)',
      sizeMb: 211,
      languages: ['en'],
      improves: "Finds photos by what's in them (English questions)",
    ),
    const ModelInfo(
      id: 'siglip2-base',
      feature: 'photo',
      name: 'SigLIP 2 base',
      tier: 'best',
      licence: 'Apache-2.0',
      source:
          'https://huggingface.co/google/siglip2-base-patch16-224 (ONNX: onnx-community/siglip2-base-patch16-224-ONNX)',
      sizeMb: 393,
      languages: ['en', 'hi', 'multilingual'],
      improves: 'Finds photos more accurately, and with questions in many languages',
      capable: false,
      capableReason: best,
    ),
    const ModelInfo(
      id: 'windows-ocr',
      feature: 'ocr',
      name: 'Windows OCR',
      tier: 'light',
      licence: 'Windows',
      source: 'Windows (Windows.Media.Ocr)',
      speedNote: 'built into Windows',
      languages: ['the Windows language packs'],
      improves: 'Reads words in photos, screenshots and scans',
      builtin: true,
      state: ModelUseState.active,
    ),
  ];
  final was = {for (final m in from?.models ?? const <ModelInfo>[]) m.id: m.state};
  return ModelsInfo(
    pc: const Hardware(
      ramGb: 15.7,
      cores: 6,
      threads: 12,
      avx2: true,
      gpu: 'Intel(R) Iris(R) Xe Graphics',
      vramGb: 0.1,
      diskFreeGb: 211.4,
      ssd: true,
    ),
    tierRecommended: 'balanced',
    tierCurrent: from?.tierCurrent ?? 'light',
    languageFocus: focus,
    models: [
      for (final m in all)
        m.withState(was[m.id] ?? m.state, recommended: m.id == text || m.id == 'siglip-base' || m.id == 'windows-ocr'),
    ],
  );
}
