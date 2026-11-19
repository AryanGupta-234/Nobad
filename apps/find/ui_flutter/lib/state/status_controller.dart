/// The engine link and its status, from events only, never polled:
/// - `status` (short, every 2 s) and `level` for the status line and the rail;
/// - `status_full` for the Indexing page, subscribed only while it's open ([watch]);
/// - `activity` (new Recent decisions on top) and `download` (model progress).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/events.dart';
import '../engine/models/format.dart';
import '../engine/models/status.dart';

class StatusController extends ChangeNotifier {
  StatusController(this.engine) : _status = engine.lastStatus {
    _sub = engine.events.listen(_event);
    engine.link.addListener(_linkChanged);
  }

  final EngineApi engine;
  late final StreamSubscription<EngineEvent> _sub;
  EngineStatus? _status;
  IndexDetails? _details;
  List<ActivityEntry> _activity = const [];
  final _downloads = <String, ModelState>{};
  var _watchers = 0;
  var _disposed = false;

  /// The short status (level, reason, phase, files, paused).
  EngineStatus? get status => _status;

  /// The Indexing page's details (null until the first status_full).
  IndexDetails? get details => _details;
  Link get link => engine.link.value;
  bool get connected => link == Link.connected;

  /// Recent decisions, newest first (the details plus activity events since).
  List<ActivityEntry> get activity => _activity;

  /// A model's download state: the newest download event, else the details.
  ModelState model(String id) =>
      _downloads[id] ?? (id == 'photo' ? _details?.photoModel : _details?.model) ?? const ModelState();

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  void _linkChanged() {
    if (connected && _watchers > 0) unawaited(_refreshDetails(subscribe: true));
    _changed();
  }

  /// The Indexing page opened (true) or closed (false): status_full is asked for once and then pushed while open.
  Future<void> watch(bool on) async {
    _watchers += on ? 1 : -1;
    if (_watchers < 0) _watchers = 0;
    if (on && _watchers == 1) {
      await _refreshDetails(subscribe: true);
    } else if (!on && _watchers == 0) {
      try {
        await engine.watchDetails(false);
      } on Object {
        // gone already
      }
    }
  }

  Future<void> _refreshDetails({bool subscribe = false}) async {
    try {
      if (subscribe) await engine.watchDetails(true);
      _takeFull(await engine.statusFull());
      _changed();
    } on Object {
      // offline: the page says so
    }
  }

  void _takeFull(EngineStatus s) {
    _details = s.details;
    _status = EngineStatus(level: s.level, reason: s.reason, phase: s.phase, files: s.files, paused: s.paused);
    final a = s.details?.activity;
    if (a != null) _activity = a;
    // A status that knows a download finished or failed replaces the progress events.
    _downloads.removeWhere((id, d) => !d.downloading);
  }

  void _event(EngineEvent e) {
    switch (e) {
      case StatusEvent(:final status):
        if (status == _status) return;
        _status = status;
      case StatusFullEvent(:final status):
        _takeFull(status);
      case LevelEvent(:final level, :final reason, :final paused):
        final s = _status ?? const EngineStatus();
        _status = EngineStatus(level: level, reason: reason, phase: s.phase, files: s.files, paused: paused);
      case ActivityEvent(:final entry):
        if (_activity.isNotEmpty && _activity.first.t == entry.t && _activity.first.text == entry.text) return;
        _activity = [entry, ..._activity.take(49)];
      case DownloadEvent():
        _downloads[e.id] = e.asState;
      case ShowEvent() || NoticeEvent() || HereEvent() || QuittingEvent():
        return;
    }
    _changed();
  }

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
    _disposed = true;
    _sub.cancel();
    engine.link.removeListener(_linkChanged);
    super.dispose();
  }
}
