/// The engine link and its short status, from the `status` event (never polled).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/events.dart';
import '../engine/models/status.dart';
import '../engine/rpc.dart';

class StatusController extends ChangeNotifier {
  StatusController(this.engine) : _status = engine.lastStatus {
    _sub = engine.events.listen((e) {
      if (e is StatusEvent && e.status != _status) {
        _status = e.status;
        notifyListeners();
      }
    });
    engine.link.addListener(notifyListeners);
  }

  final Engine engine;
  late final StreamSubscription<EngineEvent> _sub;
  EngineStatus? _status;

  EngineStatus? get status => _status;
  Link get link => engine.link.value;

  /// The status line: "12,345 files indexed · Working gently · Up to date", or what's wrong with the link.
  String get line => switch (link) {
        Link.connecting => 'Connecting to the engine…',
        Link.offline => "The engine isn't running. Trying again…",
        Link.incompatible => 'This window and the engine are different versions. Update NOBAD Find.',
        Link.connected => _connectedLine(),
      };

  String _connectedLine() {
    final s = _status;
    if (s == null) return 'Connected';
    return [
      '${groupDigits(s.files)} files indexed',
      if (s.levelLabel.isNotEmpty) s.levelLabel,
      if (s.phaseLabel.isNotEmpty) s.phaseLabel,
    ].join(' · ');
  }

  @override
  void dispose() {
    _sub.cancel();
    engine.link.removeListener(notifyListeners);
    super.dispose();
  }
}
