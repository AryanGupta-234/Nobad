/// Typed engine → UI events (nobadfind/rpc/events.py).
library;

import 'models/status.dart';

sealed class EngineEvent {
  const EngineEvent();

  /// Null for an event this UI doesn't know (newer engine): ignored.
  static EngineEvent? parse(String method, Object? params) => switch (method) {
        'status' => StatusEvent(EngineStatus.fromJson(params)),
        'show' => ShowEvent(params is Map && params['what'] is String ? params['what'] as String : 'main'),
        _ => null,
      };
}

class StatusEvent extends EngineEvent {
  const StatusEvent(this.status);
  final EngineStatus status;
}

/// A hotkey was pressed in the engine: `what` is "main" or "bar".
class ShowEvent extends EngineEvent {
  const ShowEvent(this.what);
  final String what;
}
