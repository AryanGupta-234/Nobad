/// Settings → Models (contract 0.8): the catalogue from the engine, kept current by `models` and `download` events,
/// and the actions on it. Every download asks for consent first; an engine without these methods is said plainly
/// ("needs a newer engine"), never filled in with made-up models.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/events.dart';
import '../engine/models/models_info.dart';
import '../platform/languages.dart';
import 'settings_controller.dart' show errorText;
import 'toast_controller.dart';

enum ModelsLoad { loading, ready, needsNewer, offline }

/// A download in progress (from `download` events).
class ModelProgress {
  const ModelProgress({this.gotMb = 0, this.sizeMb = 0, this.mbS = 0, this.error = ''});
  final double gotMb;
  final double sizeMb;
  final double mbS;
  final String error;
  double get fraction => sizeMb > 0 ? (gotMb / sizeMb).clamp(0, 1).toDouble() : 0;
}

class ModelsController extends ChangeNotifier {
  ModelsController(this.engine, {this.toasts, String? Function()? windowsFocus})
    : _windowsFocus = windowsFocus ?? windowsLanguageFocus {
    _sub = engine.events.listen(_event);
    engine.link.addListener(_relink);
  }

  final EngineApi engine;
  final ToastController? toasts;
  final String? Function() _windowsFocus;
  late final StreamSubscription<EngineEvent> _sub;

  ModelsLoad _load = ModelsLoad.loading;
  ModelsInfo _info = const ModelsInfo();
  String _why = '';
  final _progress = <String, ModelProgress>{};
  final _busy = <String>{};
  bool _auto = false;
  bool _disposed = false;
  LanguageFocus? _suggested;
  bool _suggestedRead = false;

  ModelsLoad get load => _load;
  ModelsInfo get info => _info;

  /// Why it couldn't load (the engine's own sentence for "needs a newer engine").
  String get why => _why;
  bool busy(String id) => _busy.contains(id);
  bool get autoBusy => _auto;
  ModelProgress? progress(String id) => _progress[id];

  /// The focus Windows' languages suggest (the engine's default before one is chosen): marked "Recommended".
  LanguageFocus? get suggestedFocus {
    if (!_suggestedRead) {
      _suggestedRead = true;
      _suggested = LanguageFocus.parse(_windowsFocus());
    }
    return _suggested;
  }

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  void _say(String s) {
    if (s.isNotEmpty) toasts?.show(s);
  }

  void _relink() {
    if (engine.link.value == Link.connected) unawaited(refresh());
  }

  Future<void> refresh() async {
    try {
      _info = await engine.models();
      _load = ModelsLoad.ready;
    } on EngineOffline {
      _load = ModelsLoad.offline;
    } on RpcException catch (e) {
      _load = e.code == -32601 ? ModelsLoad.needsNewer : ModelsLoad.offline;
      _why = e.message;
    } on Object {
      _load = ModelsLoad.offline;
    }
    _changed();
  }

  void _event(EngineEvent e) {
    switch (e) {
      case ModelsEvent(:final info):
        _info = info;
        _load = ModelsLoad.ready;
        _progress.removeWhere((id, _) => info.models.any((m) => m.id == id && m.state != ModelUseState.downloading));
      case DownloadEvent():
        if (!_info.models.any((m) => m.id == e.id)) return;
        if (e.state == 'downloading') {
          _progress[e.id] = ModelProgress(gotMb: e.gotMb, sizeMb: e.sizeMb, mbS: e.mbS);
        } else {
          _progress.remove(e.id);
          if (e.error.isNotEmpty) _say('The download stopped: ${e.error}');
        }
      default:
        return;
    }
    _changed();
  }

  Future<T?> _run<T>(String id, Future<T> Function() f) async {
    if (!_busy.add(id)) return null;
    _changed();
    try {
      return await f();
    } on Object catch (e) {
      _say(errorText(e));
      return null;
    } finally {
      _busy.remove(id);
      _changed();
    }
  }

  /// Use [m] for its feature; if it isn't downloaded yet, ask for consent and download it.
  Future<void> use(ModelInfo m, {required Future<bool> Function(ModelInfo) consent}) async {
    final r = await _run(m.id, () => engine.modelUse(m.feature, m.id));
    if (r == null) return;
    if (!r.ok) return _say(r.error.isNotEmpty ? r.error : "That model can't be used.");
    if (r.needsDownload) {
      await download(m, consent: consent);
    } else {
      _say(m.feature == 'text' ? 'Switching to ${m.name}. Search keeps working while it rebuilds.' : 'Done.');
    }
    await refresh();
  }

  /// Download [m], only after [consent] said yes (the consent word goes with the call).
  Future<bool> download(ModelInfo m, {required Future<bool> Function(ModelInfo) consent}) async {
    if (!await consent(m)) return false;
    final r = await _run(m.id, () => engine.modelDownload(m.id));
    if (r == null) return false;
    _say(r.ok ? 'Downloading ${m.name}…' : r.error);
    if (r.ok) _progress[m.id] = ModelProgress(sizeMb: m.sizeMb);
    _changed();
    return r.ok;
  }

  Future<void> remove(ModelInfo m) async {
    final r = await _run(m.id, () => engine.modelRemove(m.id));
    if (r == null) return;
    _say(r.ok ? '${m.name} removed.' : (r.error.isNotEmpty ? r.error : "It wasn't removed."));
    await refresh();
  }

  /// The recommended tier: what needs no download is applied at once; each download asks for consent.
  Future<void> autoConfigure({required Future<bool> Function(ModelInfo) consent}) async {
    if (_auto) return;
    _auto = true;
    _changed();
    try {
      final a = await engine.autoConfigure();
      await refresh();
      var asked = 0;
      for (final step in a.steps) {
        if (!step.needsDownload || step.id.isEmpty) continue;
        final m = _info.models.where((x) => x.id == step.id).firstOrNull;
        if (m == null) continue;
        asked++;
        await download(m, consent: consent);
      }
      _say(asked == 0 ? 'Set up for ${tierLabel(a.tier)}.' : '');
    } on Object catch (e) {
      _say(errorText(e));
    } finally {
      _auto = false;
      _changed();
    }
  }

  Future<void> setFocus(LanguageFocus f) async {
    if (_info.languageFocus == f) return;
    final r = await _run('focus', () => engine.modelLanguage(f.wire));
    if (r == null) return;
    if (!r.ok) _say(r.error);
    await refresh();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(_sub.cancel());
    engine.link.removeListener(_relink);
    super.dispose();
  }
}
