/// The app's engine: [EngineApi] over the pipe, and nothing else.
///
/// Every call goes to the running engine through [EngineClient]. With no engine connected a call fails with
/// [EngineOffline]; a method an older engine doesn't list in `hello.methods` fails with -32601 and a sentence.
/// The screens show that honestly (offline banners, disabled actions); nothing is ever made up here.
/// [FakeEngine] is only for tests, goldens and the explicit `NOBAD_FIND_FAKE_ENGINE=1` demo (main.dart).
///
/// One fallback that is not made up: Copy path without `path_of` uses the path the engine sent with the result.
library;

import 'package:flutter/foundation.dart';

import 'engine_api.dart';
import 'events.dart';
import 'models/models_info.dart';
import 'models/result.dart';
import 'models/settings.dart';
import 'models/status.dart';
import 'rpc.dart';

class PipeEngine implements EngineApi {
  PipeEngine(this._pipe, {this.beforeDialog});

  final EngineClient _pipe;

  /// Called with the engine's pid before a call that shows an engine dialog (AllowSetForegroundWindow).
  final void Function(int pid)? beforeDialog;
  final _known = <int, FileResult>{};

  @override
  ValueListenable<Link> get link => _pipe.link;
  @override
  Stream<EngineEvent> get events => _pipe.events;
  @override
  EngineStatus? get lastStatus => _pipe.lastStatus;

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
    if (_pipe.link.value != Link.connected) throw const EngineOffline();
    if (_pipe.serves('path_of')) return _pipe.pathOf(id);
    return _known[id]?.path ?? '';
  }

  @override
  Future<ActionResult> forget(int id) => _pipe.forget(id);
  @override
  Future<String> hereFolder() => _pipe.hereFolder();
  @override
  Future<void> toMain(String text) => _pipe.toMain(text);

  // ---- status ----
  @override
  Future<EngineStatus> status() => _pipe.status();
  @override
  Future<EngineStatus> statusFull() => _pipe.statusFull();
  @override
  Future<void> watchDetails(bool on) => _pipe.watchDetails(on);
  @override
  Future<ActionResult> pauseFor(Duration d) => _pipe.pauseFor(d);
  @override
  Future<ActionResult> resume() => _pipe.resume();
  @override
  Future<List<LearnedApp>> learnedApps() => _pipe.learnedApps();
  @override
  Future<ActionResult> resetLearned([String? exe]) => _pipe.resetLearned(exe);
  @override
  Future<Hardware?> hardware() => _pipe.hardware();

  // ---- settings and the index ----
  @override
  Future<Settings> getSettings() => _pipe.getSettings();
  @override
  Future<SettingsChange> setSettings(Map<String, Object?> changes) => _pipe.setSettings(changes);

  @override
  Future<FolderPick> pickFolder() {
    if (_pipe.enginePid != 0) beforeDialog?.call(_pipe.enginePid);
    return _pipe.pickFolder();
  }

  @override
  Future<ActionResult> rescan() => _pipe.rescan();
  @override
  Future<ActionResult> wipe(String confirm) => _pipe.wipe(confirm);
  @override
  Future<ActionResult> downloadModel(String model) => _pipe.downloadModel(model);

  // ---- Windows Search ----
  @override
  Future<WsearchState> wsearchState() => _pipe.wsearchState();

  @override
  Future<ActionResult> useInsteadOfWindowsSearch(bool on) {
    if (_pipe.enginePid != 0) beforeDialog?.call(_pipe.enginePid);
    return _pipe.useInsteadOfWindowsSearch(on);
  }

  // ---- the window ----
  @override
  Future<void> uiShown(String window) => _pipe.uiShown(window);
  @override
  Future<void> uiHidden(String window) => _pipe.uiHidden(window);
  @override
  Future<ActionResult> quit() => _pipe.quit();

  @override
  Future<ModelsInfo> models() => _pipe.models();
  @override
  Future<ModelUse> modelUse(String feature, String id) => _pipe.modelUse(feature, id);
  @override
  Future<ActionResult> modelDownload(String id) => _pipe.modelDownload(id);
  @override
  Future<ActionResult> modelRemove(String id) => _pipe.modelRemove(id);
  @override
  Future<AutoConfig> autoConfigure() => _pipe.autoConfigure();

  @override
  Future<ActionResult> openWith(int id) {
    if (_pipe.enginePid != 0) beforeDialog?.call(_pipe.enginePid);
    return _pipe.openWith(id);
  }

  @override
  void dispose() => _pipe.dispose();
}
