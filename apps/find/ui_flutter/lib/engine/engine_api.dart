/// Everything the screens can ask the engine, typed after apps/find/contract (protocol 1). Controllers depend on
/// this interface only.
///
/// Implementations:
/// - [WiredEngine] (wiring.dart): the app's engine. A method the running engine lists in `hello.methods` goes over
///   the pipe; one it doesn't serve yet (the 2026-11-18 prototype engine) is answered by [FakeEngine]. That
///   routing lives in wiring.dart only.
/// - [FakeEngine] (fake_engine.dart): an in-memory engine with the contract's shapes, for tests, screenshots and
///   the methods an older engine doesn't serve.
///
/// Files are always named by result id, never by a path from the UI (the engine looks the path up).
library;

import 'package:flutter/foundation.dart';

import 'events.dart';
import 'models/result.dart';
import 'models/settings.dart';
import 'models/status.dart';

export 'models/settings.dart' show ActionResult;

enum Link { connecting, connected, offline, incompatible }

/// The engine answered with a JSON-RPC error; [message] is plain language for the user.
class RpcException implements Exception {
  const RpcException(this.code, this.message);
  final int code;
  final String message;
  @override
  String toString() => 'RpcException($code, $message)';
}

/// No engine to talk to (not running, or the connection dropped).
class EngineOffline implements Exception {
  const EngineOffline();
}

abstract class EngineApi {
  ValueListenable<Link> get link;
  Stream<EngineEvent> get events;

  /// The newest short status seen (from `status` or its event), or null before the first one.
  EngineStatus? get lastStatus;

  // ---- search and results ----
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none});
  Future<ActionResult> open(int id);
  Future<ActionResult> reveal(int id);

  /// A small preview (PNG/JPEG/BMP bytes) from Windows' thumbnail cache, or null.
  Future<Uint8List?> thumbnail(int id);
  Future<String> pathOf(int id);

  /// Remove from the index and keep it out (adds it to Never search).
  Future<ActionResult> forget(int id);

  /// The File Explorer folder the hotkey was pressed in, or ''.
  Future<String> hereFolder();

  /// The bar's Alt+Enter: the engine brings the main window up with [text] in its box.
  Future<void> toMain(String text);

  // ---- status and the governor ----
  Future<EngineStatus> status();

  /// Everything the Indexing page shows (`status_full`).
  Future<EngineStatus> statusFull();

  /// The Indexing page is open: get `status_full` events (they cost the engine work, so only then).
  Future<void> watchDetails(bool on);
  Future<ActionResult> pauseFor(Duration d);
  Future<ActionResult> resume();
  Future<List<LearnedApp>> learnedApps();

  /// One app, or every app when [exe] is null.
  Future<ActionResult> resetLearned([String? exe]);
  Future<Hardware?> hardware();

  // ---- settings and the index ----
  Future<Settings> getSettings();
  Future<SettingsChange> setSettings(Map<String, Object?> changes);

  /// Windows' folder dialog, shown by the engine; '' if cancelled.
  Future<String> pickFolder();
  Future<ActionResult> rescan();

  /// The engine only wipes with "DELETE".
  Future<ActionResult> wipe(String confirm);

  // ---- models (progress comes as download events) ----
  /// [model] is "meaning" or "photo".
  Future<ActionResult> downloadModel(String model);

  // ---- Windows Search ----
  Future<WsearchState> wsearchState();
  Future<ActionResult> useInsteadOfWindowsSearch(bool on);

  // ---- the window and quitting ----
  /// [window] is "main" or "bar".
  Future<void> uiShown(String window);
  Future<void> uiHidden(String window);

  /// End NOBAD Find completely (the engine sends `quitting`, then closes).
  Future<ActionResult> quit();

  void dispose();
}
