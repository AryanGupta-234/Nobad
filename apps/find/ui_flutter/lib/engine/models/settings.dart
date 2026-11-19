/// Settings (const.DEFAULTS / settings.coerce in the engine) and the small records the Settings pages show:
/// learned apps (appmemory.list), the PC scan (hardware.scan), Windows Search (wsearch.state).
library;

import 'json.dart';

/// The engine's settings as it sent them. Unknown keys are kept (a newer engine), missing ones read as the
/// engine's defaults. The UI never decides what a value means: set_settings sends changes and the engine checks.
class Settings {
  const Settings(this.values);
  final Map<String, Object?> values;

  /// const.DEFAULTS in nobadfind (contract `$defs/settings`), `welcome_seen` included. An older engine whose
  /// settings don't have `welcome_seen` counts as "seen" (see [fromJson]), so its users are never nagged.
  static const defaults = <String, Object?>{
    'roots': <String>[],
    'exclude': <String>[],
    'content': true,
    'content_max_mb': 25,
    'semantic': false,
    'photo_meaning': false,
    'allow_photo_model_download': false,
    'allow_model_download': false,
    'src_mail': true,
    'ocr': true,
    'index_removable': false,
    'index_network': false,
    'pause_on_battery': true,
    'pause_fullscreen': true,
    'games_mode': 'smart',
    'keep_background': false,
    'bar': true,
    'bar_hotkey': 'ctrl+alt+space',
    'pause_on_call': true,
    'workers': 0,
    'hotkey': 'win+shift+space',
    'autostart': false,
    'hide_after_open': false,
    'wsearch_prev': '',
    'theme': 'dark',
    'glass': true,
    'bg_notice_seen': false,
    'welcome_seen': false,
    'search_history': true,
  };

  static const initial = Settings(defaults);

  static Settings fromJson(Object? json) {
    final m = jMap(json);
    return Settings({...defaults, if (!m.containsKey('welcome_seen')) 'welcome_seen': true, ...m});
  }

  Object? operator [](String key) => values.containsKey(key) ? values[key] : defaults[key];
  bool flag(String key) => this[key] == true;
  String text(String key) => jStr(this[key]);
  int number(String key) => jInt(this[key]);
  List<String> list(String key) => jStrs(this[key]);

  /// 0.8.5 is dark only (maintainer decision 2026-11-19), whatever an older engine says.
  bool get dark => true;
  bool get glass => flag('glass');

  Settings merged(Map<String, Object?> changes) => Settings({...values, ...changes});
}

/// `set_settings` answer: what really changed, and the settings after it.
class SettingsChange {
  const SettingsChange(this.changed, this.settings);
  final List<String> changed;
  final Settings settings;

  static SettingsChange fromJson(Object? v) {
    final m = jMap(v);
    return SettingsChange(jStrs(m['changed']), Settings.fromJson(m['settings']));
  }
}

class LearnedApp {
  const LearnedApp({required this.exe, this.seen = 0, this.lagEvents = 0, this.startLevel, this.reason = ''});
  final String exe;
  final int seen;
  final int lagEvents;
  final String? startLevel;
  final String reason;

  /// `learned_apps` answer: `{apps: [...]}`.
  static List<LearnedApp> listFromJson(Object? v) => jList(jMap(v)['apps'], fromJson);

  /// "game" from "game.exe": only the file name is ever stored.
  String get bare => exe.replaceAll(RegExp(r'\.exe$', caseSensitive: false), '');

  static LearnedApp? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['exe']).isEmpty) return null;
    return LearnedApp(
      exe: jStr(m['exe']),
      seen: jInt(m['seen']),
      lagEvents: jInt(m['lag_events']),
      startLevel: m['start_level'] is String ? m['start_level'] as String : null,
      reason: jStr(m['reason']),
    );
  }
}

class Hardware {
  const Hardware({
    this.ramGb = 0,
    this.cores = 0,
    this.threads = 0,
    this.avx2 = false,
    this.avx512Vnni = false,
    this.gpu = '',
    this.vramGb = 0,
    this.directml = false,
    this.diskFreeGb = 0,
    this.ssd,
  });
  final double ramGb;
  final int cores;
  final int threads;
  final bool avx2;
  final bool avx512Vnni;
  final String gpu;
  final double vramGb;
  final bool directml;
  final double diskFreeGb;
  final bool? ssd;

  static Hardware? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return Hardware(
      ramGb: jNum(m['ram_gb']),
      cores: jInt(m['cores']),
      threads: jInt(m['threads']),
      avx2: jBool(m['avx2']),
      avx512Vnni: jBool(m['avx512_vnni']),
      gpu: jStr(m['gpu']),
      vramGb: jNum(m['vram_gb']),
      directml: jBool(m['directml']),
      diskFreeGb: jNum(m['disk_free_gb']),
      ssd: m['ssd'] is bool ? m['ssd'] as bool : null,
    );
  }
}

class WsearchState {
  const WsearchState({this.missing = false, this.start = '', this.running = false, this.saved = ''});
  final bool missing;

  /// How it started before NOBAD Find turned it off ('' if it didn't).
  final String saved;

  /// auto | delayed-auto | demand | disabled
  final String start;
  final bool running;
  bool get off => start == 'disabled';

  static WsearchState fromJson(Object? v) {
    final m = jMap(v);
    if (m.isEmpty || jBool(m['missing'])) return const WsearchState(missing: true);
    return WsearchState(start: jStr(m['start']), running: jBool(m['running']), saved: jStr(m['saved']));
  }
}

/// `pick_folder` answer: the folder ('' if cancelled); [busy] = a folder window was already open (not a cancel).
class FolderPick {
  const FolderPick(this.path, {this.busy = false});
  final String path;
  final bool busy;

  static FolderPick fromJson(Object? v) {
    final m = jMap(v);
    return FolderPick(jStr(m['path']), busy: jBool(m['busy']));
  }
}

/// The engine refuses longer words, folders and handed-over text (contract: at most 2000 characters).
const maxTextLength = 2000;

/// `Ok` = `{ok, error}` (open, reveal, forget, downloads, wipe, quit…); wsearch_set adds `state`.
class ActionResult {
  const ActionResult(this.ok, [this.error = '']);
  final bool ok;
  final String error;

  static ActionResult fromJson(Object? v) {
    final m = jMap(v);
    return ActionResult(jBool(m['ok']), jStr(m['error']));
  }
}
