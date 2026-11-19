/// Settings and the actions on the Settings pages: changes go to the engine, which checks them; downloads ask for
/// consent first; the dangerous ones (wipe, forget every app) ask for confirmation. Messages are the 0.7.0 words.
library;

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/models/settings.dart';

import 'toast_controller.dart';

class SettingsController extends ChangeNotifier {
  SettingsController(this.engine, {this.toasts});

  final EngineApi engine;
  final ToastController? toasts;

  Settings _settings = Settings.initial;
  bool _loaded = false;
  List<LearnedApp> _learned = const [];
  Hardware? _hardware;
  WsearchState? _wsearch;
  bool _wsearchBusy = false;
  bool _disposed = false;

  Settings get settings => _settings;
  bool get loaded => _loaded;
  List<LearnedApp> get learned => _learned;
  Hardware? get hardware => _hardware;
  WsearchState? get wsearch => _wsearch;
  bool get wsearchBusy => _wsearchBusy;

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  void _say(String s) => toasts?.show(s);

  Future<void> load() async {
    try {
      _settings = await engine.getSettings();
      _loaded = true;
    } on EngineOffline {
      // keeps the last known settings
    } on RpcException {
      // same
    }
    _changed();
  }

  /// The Settings pages' extra blocks: learned apps, the PC scan, Windows Search.
  Future<void> loadExtras() async {
    try {
      final r = await Future.wait([engine.learnedApps(), engine.hardware(), engine.wsearchState()]);
      _learned = r[0] as List<LearnedApp>;
      _hardware = r[1] as Hardware?;
      _wsearch = r[2] as WsearchState;
    } on Object {
      // shown as "not available"
    }
    _changed();
  }

  /// Change one setting. Shown at once; if the engine doesn't take it, says so and shows the real value again.
  Future<bool> set(String key, Object? value) async {
    final before = _settings;
    _settings = _settings.merged({key: value});
    _changed();
    SettingsChange r;
    try {
      r = await engine.setSettings({key: value});
    } on Object {
      _say("NOBAD Find's engine isn't running.");
      _settings = before;
      _changed();
      return false;
    }
    _settings = r.settings;
    _changed();
    final now = r.settings[key];
    final took = now is List && value is List ? listEquals(now, value) : now == value;
    if (!took) _say("That value wasn't accepted.");
    return took;
  }

  Future<void> addFolder(String key, String path) async {
    if (path.isEmpty) return;
    final list = _settings.list(key);
    if (list.contains(path)) return;
    await set(key, [...list, path]);
  }

  /// "Add folder": Windows' folder dialog (the engine shows it), then the folder joins the list.
  Future<void> pickAndAdd(String key) async {
    String path;
    try {
      path = await engine.pickFolder();
    } on Object {
      return;
    }
    await addFolder(key, path);
  }

  Future<void> removeFolder(String key, int index) async {
    final list = [..._settings.list(key)];
    if (index < 0 || index >= list.length) return;
    list.removeAt(index);
    await set(key, list);
  }

  /// [model] "meaning" or "photo". [consent] shows the consent dialog; nothing is downloaded without a yes.
  Future<bool> download(String model, {required Future<bool> Function() consent}) async {
    if (!await consent()) return false;
    final allow = model == 'photo' ? 'allow_photo_model_download' : 'allow_model_download';
    if (!_settings.flag(allow) && !await set(allow, true)) return false;
    ActionResult r;
    try {
      r = await engine.downloadModel(model);
    } on Object {
      r = const ActionResult(false, "NOBAD Find's engine isn't running.");
    }
    _say(r.ok ? (model == 'photo' ? 'Downloading the photo model…' : 'Downloading the model…') : r.error);
    return r.ok;
  }

  Future<void> forgetApp(String? exe, {Future<bool> Function()? confirm}) async {
    if (exe == null && confirm != null && !await confirm()) return;
    try {
      if (!(await engine.resetLearned(exe)).ok) return;
      _say('Forgotten.');
    } on Object {
      return;
    }
    await loadExtras();
  }

  Future<void> toggleWindowsSearch() async {
    final ws = _wsearch;
    if (ws == null || ws.missing || _wsearchBusy) return;
    _wsearchBusy = true;
    _changed();
    try {
      final r = await engine.useInsteadOfWindowsSearch(!ws.off);
      _say(r.ok ? 'Done.' : (r.error.isNotEmpty ? r.error : 'No change.'));
    } on Object {
      _say('No change.');
    }
    _wsearchBusy = false;
    await Future.wait([loadExtras(), load()]);
  }

  /// [ask] shows "Type DELETE to confirm" and returns what was typed (null: cancelled).
  Future<bool> wipe(Future<String?> Function() ask) async {
    if (await ask() != 'DELETE') return false;
    try {
      if ((await engine.wipe('DELETE')).ok) {
        _say('Index deleted. Rebuilding.');
        return true;
      }
    } on Object {
      // falls through
    }
    return false;
  }

  Future<void> rescan() async {
    try {
      await engine.rescan();
      _say('Rescan started.');
    } on Object {
      _say("NOBAD Find's engine isn't running.");
    }
  }

  /// Quit NOBAD Find completely (the engine says `quitting`, then the window closes).
  Future<void> quit() async {
    try {
      await engine.quit();
    } on Object {
      // the engine is gone already
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
