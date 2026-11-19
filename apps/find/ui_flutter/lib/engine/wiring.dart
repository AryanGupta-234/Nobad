/// Which [EngineApi] call goes to the real engine and which, for now, to [FakeEngine]. **The one place that
/// decides it.**
///
/// The engine says what it serves: `hello` lists its `methods` and `events` (contract README). A method on that
/// list goes over the pipe ([EngineClient] has a typed call for every contract method); one that isn't is answered
/// by [FakeEngine], with the same shapes, so every screen works. An event the engine doesn't list comes from the
/// fake. So with the full engine (branch find-engine-rpc) nothing is fake, and with the 2026-11-18 prototype engine
/// (hello without `methods`: hello, subscribe, search, open, reveal, thumbnail, status) this is what's faked:
///
/// | EngineApi                         | contract method                     | prototype engine |
/// |-----------------------------------|-------------------------------------|------------------|
/// | search, open, reveal, thumbnail   | same names                          | pipe |
/// | status                            | status                              | pipe |
/// | statusFull, watchDetails          | status_full (method and event)      | fake details + the real short status |
/// | pathOf                            | path_of                             | `Result.path`, else dir + name of the last results |
/// | forget, hereFolder, toMain        | forget, here_folder, to_main        | fake |
/// | pauseFor, resume                  | pause_for, resume                   | fake |
/// | learnedApps, resetLearned         | learned_apps, reset_learned         | fake |
/// | hardware                          | hardware                            | fake |
/// | getSettings, setSettings          | get_settings, set_settings          | fake (theme and glass apply; nothing is saved) |
/// | pickFolder                        | pick_folder                         | fake (no dialog) |
/// | rescan, wipe                      | rescan, wipe                        | fake |
/// | downloadModel                     | download_model, download_photo_model| fake (simulated progress events) |
/// | wsearchState, useInsteadOf…       | wsearch_state, use_instead_of_windows_search | fake |
/// | uiShown, uiHidden, quit           | ui_shown, ui_hidden, quit           | fake |
/// | events level, activity, download, notice, here, quitting, status_full |   | fake |
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'engine_api.dart';
import 'events.dart';
import 'fake_engine.dart';
import 'models/result.dart';
import 'models/settings.dart';
import 'models/status.dart';
import 'rpc.dart';

class WiredEngine implements EngineApi {
  WiredEngine(this._pipe, {FakeEngine? fake, this.beforeDialog})
    : _fake = fake ?? FakeEngine(files: const [], live: true, settings: const {}) {
    _subs = [_pipe.events.listen(_fromPipe), _fake.events.listen(_fromFake)];
  }

  final EngineClient _pipe;
  final FakeEngine _fake;

  /// Called with the engine's pid before a call that shows an engine dialog (AllowSetForegroundWindow).
  final void Function(int pid)? beforeDialog;
  late final List<StreamSubscription<EngineEvent>> _subs;
  final _events = StreamController<EngineEvent>.broadcast();
  final _known = <int, FileResult>{};

  bool _serves(String method) => _pipe.served.contains(method);

  /// The events a prototype engine doesn't push (a full engine lists them in hello.events and pushes them all).
  bool _pipeSends(EngineEvent e) => switch (e) {
    StatusEvent() || ShowEvent() => true,
    StatusFullEvent() => _serves('status_full'),
    DownloadEvent() => _serves('download_model'),
    HereEvent() => _serves('here_folder'),
    QuittingEvent() => _serves('quit'),
    LevelEvent() || ActivityEvent() => _serves('status_full'),
    NoticeEvent() => _serves('status_full'),
  };

  @override
  ValueListenable<Link> get link => _pipe.link;
  @override
  Stream<EngineEvent> get events => _events.stream;
  @override
  EngineStatus? get lastStatus => _pipe.lastStatus;

  void _add(EngineEvent e) {
    if (!_events.isClosed) _events.add(e);
  }

  void _fromPipe(EngineEvent e) => _add(e);

  void _fromFake(EngineEvent e) {
    if (_pipeSends(e)) return; // the real one comes from the engine
    if (e is StatusFullEvent) {
      final brief = _pipe.lastStatus;
      _add(brief == null ? e : StatusFullEvent(e.status.withBrief(brief)));
    } else {
      _add(e);
    }
  }

  // ---- search and results ----
  @override
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none}) async {
    final a = await _pipe.search(text, filters: filters);
    if (_known.length > 2000) _known.clear();
    for (final r in a.results) {
      _known[r.id] = r;
    }
    return a;
  }

  @override
  Future<ActionResult> open(int id) => _pipe.open(id);
  @override
  Future<ActionResult> reveal(int id) => _pipe.reveal(id);
  @override
  Future<Uint8List?> thumbnail(int id) => _pipe.thumbnail(id);

  @override
  Future<String> pathOf(int id) async {
    if (_serves('path_of')) return _pipe.pathOf(id);
    final r = _known[id];
    if (r == null) return '';
    if (r.path.isNotEmpty) return r.path;
    return r.dir.isEmpty ? '' : '${r.dir}${r.dir.endsWith('\\') ? '' : '\\'}${r.name}';
  }

  @override
  Future<ActionResult> forget(int id) => _serves('forget') ? _pipe.forget(id) : _fake.forget(id);
  @override
  Future<String> hereFolder() => _serves('here_folder') ? _pipe.hereFolder() : _fake.hereFolder();
  @override
  Future<void> toMain(String text) => _serves('to_main') ? _pipe.toMain(text) : _fake.toMain(text);

  // ---- status ----
  @override
  Future<EngineStatus> status() => _pipe.status();

  @override
  Future<EngineStatus> statusFull() async {
    if (_serves('status_full')) return _pipe.statusFull();
    final f = await _fake.statusFull();
    final brief = _pipe.lastStatus;
    return brief == null ? f : f.withBrief(brief);
  }

  @override
  Future<void> watchDetails(bool on) => _serves('status_full') ? _pipe.watchDetails(on) : _fake.watchDetails(on);
  @override
  Future<ActionResult> pauseFor(Duration d) => _serves('pause_for') ? _pipe.pauseFor(d) : _fake.pauseFor(d);
  @override
  Future<ActionResult> resume() => _serves('resume') ? _pipe.resume() : _fake.resume();
  @override
  Future<List<LearnedApp>> learnedApps() => _serves('learned_apps') ? _pipe.learnedApps() : _fake.learnedApps();
  @override
  Future<ActionResult> resetLearned([String? exe]) =>
      _serves('reset_learned') ? _pipe.resetLearned(exe) : _fake.resetLearned(exe);
  @override
  Future<Hardware?> hardware() => _serves('hardware') ? _pipe.hardware() : _fake.hardware();

  // ---- settings and the index ----
  @override
  Future<Settings> getSettings() => _serves('get_settings') ? _pipe.getSettings() : _fake.getSettings();
  @override
  Future<SettingsChange> setSettings(Map<String, Object?> changes) =>
      _serves('set_settings') ? _pipe.setSettings(changes) : _fake.setSettings(changes);

  @override
  Future<FolderPick> pickFolder() {
    if (!_serves('pick_folder')) return _fake.pickFolder();
    if (_pipe.enginePid != 0) beforeDialog?.call(_pipe.enginePid);
    return _pipe.pickFolder();
  }

  @override
  Future<ActionResult> rescan() => _serves('rescan') ? _pipe.rescan() : _fake.rescan();
  @override
  Future<ActionResult> wipe(String confirm) => _serves('wipe') ? _pipe.wipe(confirm) : _fake.wipe(confirm);

  @override
  Future<ActionResult> downloadModel(String model) =>
      _serves(model == 'photo' ? 'download_photo_model' : 'download_model')
      ? _pipe.downloadModel(model)
      : _fake.downloadModel(model);

  // ---- Windows Search ----
  @override
  Future<WsearchState> wsearchState() => _serves('wsearch_state') ? _pipe.wsearchState() : _fake.wsearchState();

  @override
  Future<ActionResult> useInsteadOfWindowsSearch(bool on) {
    if (!_serves('use_instead_of_windows_search')) return _fake.useInsteadOfWindowsSearch(on);
    if (_pipe.enginePid != 0) beforeDialog?.call(_pipe.enginePid);
    return _pipe.useInsteadOfWindowsSearch(on);
  }

  // ---- the window ----
  @override
  Future<void> uiShown(String window) => _serves('ui_shown') ? _pipe.uiShown(window) : _fake.uiShown(window);
  @override
  Future<void> uiHidden(String window) => _serves('ui_hidden') ? _pipe.uiHidden(window) : _fake.uiHidden(window);
  @override
  Future<ActionResult> quit() => _serves('quit') ? _pipe.quit() : _fake.quit();

  @override
  void dispose() {
    for (final s in _subs) {
      s.cancel();
    }
    _fake.dispose();
    _pipe.dispose();
    _events.close();
  }
}
