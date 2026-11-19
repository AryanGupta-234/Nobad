/// Typed engine → UI events, exactly as apps/find/contract/events.schema.json (protocol 1): status, status_full,
/// level, activity, download, notice, show, here, quitting. The UI never polls: everything that changes on its own
/// changes from these.
library;

import 'models/json.dart';
import 'models/models_info.dart';
import 'models/status.dart';

sealed class EngineEvent {
  const EngineEvent();

  /// What the main window subscribes to (status_full only while the Indexing page is open).
  static const mainWindow = [
    'status', 'level', 'activity', 'download', 'notice', 'show', 'here', 'quitting', 'models', //
  ];

  /// What the quick find bar subscribes to.
  static const bar = ['show', 'quitting'];

  /// Null for an event this UI doesn't know (a newer engine): ignored.
  static EngineEvent? parse(String method, Object? params) {
    final m = jMap(params);
    switch (method) {
      case 'status':
        return StatusEvent(EngineStatus.fromJson(params));
      case 'status_full':
        return StatusFullEvent(EngineStatus.fromJson({...m, 'phases': m['phases'] ?? const []}));
      case 'level':
        return LevelEvent(jStr(m['level']), jStr(m['reason']), paused: jStr(m['paused']));
      case 'activity':
        final e = ActivityEntry.fromJson(params);
        return e == null ? null : ActivityEvent(e);
      case 'download':
        final id = jStr(m['id']);
        if (id.isEmpty) return null;
        return DownloadEvent(
          id: id,
          state: jStr(m['state']),
          gotMb: jNum(m['got_mb']),
          sizeMb: jNum(m['size_mb']),
          mbS: jNum(m['mb_s']),
          error: jStr(m['error']),
        );
      case 'notice':
        return jStr(m['text']).isEmpty ? null : NoticeEvent(jStr(m['text']));
      case 'show':
        final t = m['text'];
        final what = jStr(m['what']);
        return ShowEvent(
          const {'bar', 'settings', 'index'}.contains(what) ? what : 'main',
          text: t is String ? t : null,
        );
      case 'models':
        return ModelsEvent(ModelsInfo.fromJson(params));
      case 'here':
        return HereEvent(jStr(m['path']));
      case 'quitting':
        return const QuittingEvent();
    }
    return null;
  }
}

/// The short status (every 2 s).
class StatusEvent extends EngineEvent {
  const StatusEvent(this.status);
  final EngineStatus status;
}

/// Everything the Indexing page shows (every 2 s, only while subscribed).
class StatusFullEvent extends EngineEvent {
  const StatusFullEvent(this.status);
  final EngineStatus status;
}

/// Bring a window up. [what] "main", "bar", or a main-window page from the engine's tray menu: "settings", "index". [text] null: a hotkey (keep the box); a string: the bar's Alt+Enter.
class ShowEvent extends EngineEvent {
  const ShowEvent(this.what, {this.text});
  final String what;
  final String? text;
}

/// The File Explorer folder the main hotkey was pressed in ('' if none).
class HereEvent extends EngineEvent {
  const HereEvent(this.path);
  final String path;
}

/// The work level, its reason or the pause changed.
class LevelEvent extends EngineEvent {
  const LevelEvent(this.level, this.reason, {this.paused = ''});
  final String level;
  final String reason;
  final String paused;
}

/// One new line for "Recent decisions".
class ActivityEvent extends EngineEvent {
  const ActivityEvent(this.entry);
  final ActivityEntry entry;
}

/// A model download moved on: [id] "meaning" or "photo"; [state] downloading | ready | missing (failed: [error]).
class DownloadEvent extends EngineEvent {
  const DownloadEvent({
    required this.id,
    required this.state,
    this.gotMb = 0,
    this.sizeMb = 0,
    this.mbS = 0,
    this.error = '',
  });
  final String id;
  final String state;
  final double gotMb;
  final double sizeMb;
  final double mbS;
  final String error;

  ModelState get asState => ModelState(
    state: state,
    got: (gotMb * 1048576).round(),
    size: (sizeMb * 1048576).round(),
    error: error,
    mbS: mbS,
  );
}

/// The model catalogue changed (a download finished, a model was put in use or removed).
class ModelsEvent extends EngineEvent {
  const ModelsEvent(this.info);
  final ModelsInfo info;
}

/// A sentence for a toast.
class NoticeEvent extends EngineEvent {
  const NoticeEvent(this.text);
  final String text;
}

/// The engine is ending: exit instead of reconnecting.
class QuittingEvent extends EngineEvent {
  const QuittingEvent();
}
