/// JSON-RPC 2.0 to the engine: request ids, timeouts, typed calls, events, and reconnecting with backoff.
///
/// The transport (the named pipe, or a fake in tests) only moves lines; everything about the protocol is here.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';

import 'engine_api.dart';
import 'events.dart';
import 'models/json.dart';
import 'models/models_info.dart';
import 'models/scope_info.dart';
import 'models/result.dart';
import 'models/settings.dart';
import 'models/status.dart';

export 'engine_api.dart' show EngineOffline, Link, RpcException;

const protocolVersion = 1;
const maxMessage = 1024 * 1024;

/// Moves whole lines (one JSON object each) to and from the engine.
abstract class Transport {
  /// Incoming lines; the stream ends when the connection is gone.
  Stream<String> get lines;
  void send(String line);
  Future<void> close();
}

typedef Connector = Future<Transport> Function();

/// One connection's request/response bookkeeping.
class RpcSession {
  // ignore: prefer_initializing_formals
  RpcSession(this._t, {required void Function(EngineEvent) onEvent}) : _onEvent = onEvent {
    _sub = _t.lines.listen(_line, onDone: _closed, onError: (_) => _closed());
  }

  final Transport _t;
  final void Function(EngineEvent) _onEvent;
  late final StreamSubscription<String> _sub;
  final _pending = <int, Completer<Object?>>{};
  final _done = Completer<void>();
  var _next = 1;

  Future<void> get done => _done.future;
  bool get isOpen => !_done.isCompleted;

  Future<Object?> call(String method, [Map<String, Object?> params = const {}, Duration? timeout]) {
    if (!isOpen) return Future.error(const EngineOffline());
    final id = _next++;
    final String line;
    try {
      line = jsonEncode({'jsonrpc': '2.0', 'id': id, 'method': method, 'params': params});
    } on Object {
      return Future.error(const RpcException(-32600, "That request couldn't be sent."));
    }
    final c = Completer<Object?>();
    _pending[id] = c;
    try {
      _t.send(line);
    } catch (_) {
      _pending.remove(id);
      _closed();
      return Future.error(const EngineOffline());
    }
    return c.future.timeout(
      timeout ?? const Duration(seconds: 15),
      onTimeout: () {
        _pending.remove(id);
        throw const RpcException(-32000, 'The engine took too long to answer.');
      },
    );
  }

  void _line(String line) {
    Object? msg;
    try {
      msg = jsonDecode(line);
    } catch (_) {
      return; // not ours to crash on
    }
    if (msg is! Map) return;
    final id = msg['id'];
    if (id is int && _pending.containsKey(id)) {
      final c = _pending.remove(id)!;
      final err = msg['error'];
      if (err is Map) {
        c.completeError(
          RpcException(
            err['code'] is int ? err['code'] as int : -32603,
            err['message'] is String ? err['message'] as String : 'Error',
          ),
        );
      } else {
        c.complete(msg['result']);
      }
      return;
    }
    if (msg.containsKey('id') && msg['id'] == null && msg['error'] is Map) {
      final err = msg['error'] as Map;
      final e = RpcException(
        err['code'] is int ? err['code'] as int : -32700,
        err['message'] is String ? err['message'] as String : 'The engine could not read a request.',
      );
      for (final c in _pending.values) {
        c.completeError(e);
      }
      _pending.clear();
      return;
    }
    final method = msg['method'];
    if (method is String && !msg.containsKey('id')) {
      final ev = EngineEvent.parse(method, msg['params']);
      if (ev != null) _onEvent(ev);
    }
  }

  void _closed() {
    if (_done.isCompleted) return;
    for (final c in _pending.values) {
      c.completeError(const EngineOffline());
    }
    _pending.clear();
    _done.complete();
    _sub.cancel();
    _t.close();
  }

  Future<void> close() async => _closed();
}

/// The real engine over the pipe: the connection, its events, and a typed call for every contract method.
/// Screens use it through [PipeEngine] (wiring.dart). A call the connected engine doesn't serve fails with
/// -32601; with no engine connected every call fails with [EngineOffline]. Nothing is ever made up.
class EngineClient {
  EngineClient(
    this._connect, {
    List<Duration>? backoff,
    this.log,
    this.subscribeTo = EngineEvent.mainWindow,
    this.window = 'main',
  }) : _backoff =
           backoff ??
           const [
             Duration(milliseconds: 200),
             Duration(milliseconds: 500),
             Duration(seconds: 1),
             Duration(seconds: 2),
             Duration(seconds: 4),
           ];

  final Connector _connect;
  final List<Duration> _backoff;
  final void Function(String)? log;

  /// The events this window wants (contract README, "Start-up order for a UI").
  final List<String> subscribeTo;

  /// "main" or "bar", for ui_shown / ui_hidden.
  final String window;
  final _link = ValueNotifier(Link.connecting);
  final _events = StreamController<EngineEvent>.broadcast();
  final _thumbs = <int, Uint8List?>{}; // insertion-ordered: the first key is the least recently used
  final _thumbsInFlight = <int, Future<Uint8List?>>{};
  static const _thumbCache = 300;
  RpcSession? _rpc;
  EngineStatus? _last;
  var _disposed = false;
  var _started = false;
  var _quitting = false;
  var _watching = false;

  /// Is this UI's window on screen? Reported again after a reconnect (the engine starts idle until a window shows).
  late bool _shown = window == 'main';
  bool get shown => _shown;

  /// Order-sensitive calls of one kind wait for the previous one (the engine answers on a pool of threads).
  final _queues = <String, Future<void>>{};

  Future<T> _inOrder<T>(String kind, Future<T> Function() f) {
    final prev = _queues[kind] ?? Future<void>.value();
    final next = prev.then((_) => f());
    _queues[kind] = next.then((_) {}, onError: (_) {});
    return next;
  }

  /// Methods every engine has (no need to be listed).
  static const _always = {'hello', 'subscribe', 'unsubscribe'};

  bool serves(String method) => _always.contains(method) || served.contains(method);

  /// What the connected engine serves (`hello.methods`); the prototype engine's list when it doesn't say.
  Set<String> served = const {};

  /// The engine's process id (`hello.pid`), for AllowSetForegroundWindow before its dialogs; 0 if unknown.
  int enginePid = 0;

  ValueListenable<Link> get link => _link;
  Stream<EngineEvent> get events => _events.stream;
  EngineStatus? get lastStatus => _last;

  /// The engine said it is quitting: no reconnecting.
  bool get quitting => _quitting;

  /// Connects now and keeps reconnecting (with backoff) for as long as the client lives.
  void start() {
    if (_started) return;
    _started = true;
    unawaited(_loop());
  }

  Future<void> _loop() async {
    var attempt = 0;
    while (!_disposed && !_quitting) {
      RpcSession? rpc;
      try {
        final t = await _connect();
        if (_disposed) {
          await t.close();
          return;
        }
        rpc = RpcSession(t, onEvent: _event);
        final hello = await rpc.call('hello', const {}, const Duration(seconds: 5));
        final h = hello is Map ? hello : const {};
        final v = h['protocol'];
        if (v != protocolVersion) {
          log?.call('engine speaks protocol $v, this UI $protocolVersion');
          _link.value = Link.incompatible;
          await rpc.close();
          await Future<void>.delayed(const Duration(seconds: 10));
          continue;
        }
        final methods = h['methods'];
        served = methods is List
            ? {
                for (final m in methods)
                  if (m is String) m,
              }
            : prototypeMethods;
        enginePid = h['pid'] is int ? h['pid'] as int : 0;
        await rpc.call('subscribe', {
          'events': [...subscribeTo, if (_watching && served.contains('status_full')) 'status_full'],
        });
        _rpc = rpc;
        attempt = 0;
        _thumbs.clear(); // the index may have changed while we were away
        _link.value = Link.connected;
        unawaited(rpc.call('status').then((s) => _event(StatusEvent(EngineStatus.fromJson(s))), onError: (_) {}));
        // what the window really is: a new connection counts as not shown until it says so
        if (_shown && served.contains('ui_shown')) {
          unawaited(rpc.call('ui_shown', {'window': window}).then((_) {}, onError: (_) {}));
        }
        await rpc.done;
      } catch (e) {
        log?.call('engine connection: $e');
        await rpc?.close();
      }
      _rpc = null;
      if (_disposed) return;
      _link.value = Link.offline;
      if (_quitting) return;
      await Future<void>.delayed(_backoff[attempt < _backoff.length ? attempt : _backoff.length - 1]);
      attempt++;
    }
  }

  void _event(EngineEvent e) {
    if (e is StatusEvent) _last = e.status;
    if (e is QuittingEvent) _quitting = true;
    if (!_events.isClosed) _events.add(e);
  }

  /// Any method by name (EngineOffline when not connected; RpcException for an engine error).
  /// [wait] false: no time limit (dialogs the user answers: pick_folder, wsearch_set).
  Future<Object?> call(String method, [Map<String, Object?> params = const {}, bool wait = true]) {
    final rpc = _rpc;
    if (rpc == null || !rpc.isOpen) return Future.error(const EngineOffline());
    if (!serves(method)) return Future.error(const RpcException(-32601, notServed));
    return rpc.call(method, params, wait ? null : const Duration(days: 1));
  }

  static const notServed = "This version of NOBAD Find's engine can't do that yet. Update NOBAD Find.";

  /// Forget every preview (after a wipe, a forget, or a reconnect).
  void clearThumbs() => _thumbs.clear();

  Future<ActionResult> _ok(String method, [Map<String, Object?> params = const {}, bool wait = true]) async =>
      ActionResult.fromJson(await call(method, params, wait));

  // ---- search and results ----
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none}) async =>
      SearchAnswer.fromJson(await call('search', {'text': _cap(text), 'filters': filters.toJson()}));
  Future<ActionResult> open(int id) => _ok('open', {'id': id});
  Future<ActionResult> reveal(int id) => _ok('reveal', {'id': id});
  Future<ActionResult> forget(int id) async {
    final r = await _ok('forget', {'id': id});
    _thumbs.remove(id);
    return r;
  }

  Future<String> pathOf(int id) async => jStr(jMap(await call('path_of', {'id': id}))['path']);
  Future<String> hereFolder() async => jStr(jMap(await call('here_folder'))['path']);
  Future<void> toMain(String text) => call('to_main', {'text': _cap(text)});

  /// The engine refuses longer text (-32602): cut it, never at half a character.
  static String _cap(String s) {
    if (s.length <= maxTextLength) return s;
    var n = maxTextLength;
    if ((s.codeUnitAt(n - 1) & 0xFC00) == 0xD800) n--;
    return s.substring(0, n);
  }

  // ---- status ----
  Future<EngineStatus> status() async {
    final s = EngineStatus.fromJson(await call('status'));
    _last = s;
    return s;
  }

  Future<EngineStatus> statusFull() async {
    final m = jMap(await call('status_full'));
    return EngineStatus.fromJson({...m, 'phases': m['phases'] ?? const []});
  }

  Future<void> watchDetails(bool on) {
    _watching = on;
    if (!served.contains('status_full')) return Future.value();
    return _inOrder('details', () async {
      if (_watching != on) return; // a newer wish came in while waiting
      await call(on ? 'subscribe' : 'unsubscribe', {
        'events': ['status_full'],
      });
    });
  }

  Future<ActionResult> pauseFor(Duration d) => _ok('pause_for', {'seconds': d.inSeconds.clamp(1, 86400)});
  Future<ActionResult> resume() => _ok('resume');
  Future<List<LearnedApp>> learnedApps() async => LearnedApp.listFromJson(await call('learned_apps'));
  Future<ActionResult> resetLearned([String? exe]) => _ok('reset_learned', {'exe': exe});
  Future<Hardware?> hardware() async => Hardware.fromJson(await call('hardware'));

  // ---- settings and the index ----
  Future<Settings> getSettings() async => Settings.fromJson(await call('get_settings'));
  Future<SettingsChange> setSettings(Map<String, Object?> changes) =>
      _inOrder('settings', () async => SettingsChange.fromJson(await call('set_settings', {'changes': changes})));
  Future<FolderPick> pickFolder() async => FolderPick.fromJson(await call('pick_folder', const {}, false));
  Future<ActionResult> rescan() => _ok('rescan');
  Future<ActionResult> wipe(String confirm) async {
    final r = await _ok('wipe', {'confirm': confirm});
    if (r.ok) _thumbs.clear();
    return r;
  }

  // ---- models ----
  Future<ActionResult> downloadModel(String model) => _ok(model == 'photo' ? 'download_photo_model' : 'download_model');

  // ---- Windows Search ----
  Future<WsearchState> wsearchState() async => WsearchState.fromJson(await call('wsearch_state'));
  Future<ActionResult> useInsteadOfWindowsSearch(bool on) => _ok('use_instead_of_windows_search', {'on': on}, false);

  // ---- the window ----
  Future<void> uiShown(String window) {
    _shown = true;
    return _inOrder('window', () => _shown ? call('ui_shown', {'window': window}) : Future.value());
  }

  Future<void> uiHidden(String window) {
    _shown = false;
    return _inOrder('window', () => _shown ? Future.value() : call('ui_hidden', {'window': window}));
  }

  Future<ActionResult> quit() => _ok('quit', {'confirm': 'QUIT'});

  // ---- 0.8 ----
  Future<ModelsInfo> models() async => ModelsInfo.fromJson(await call('models'));
  Future<ModelUse> modelUse(String feature, String id) async =>
      ModelUse.fromJson(await call('model_use', {'feature': feature, 'id': id}));
  Future<ActionResult> modelDownload(String id) => _ok('model_download', {'id': id, 'consent': 'DOWNLOAD'});
  Future<ActionResult> modelRemove(String id) => _ok('model_remove', {'id': id});
  Future<AutoConfig> autoConfigure() async => AutoConfig.fromJson(await call('auto_configure'));
  Future<ActionResult> modelLanguage(String focus) => _ok('model_language', {'focus': focus});
  Future<ActionResult> openWith(int id) => _ok('open_with', {'id': id}, false);
  Future<ScopeInfo> scopeInfo() async => ScopeInfo.fromJson(await call('scope_info'));
  Future<TurboState> turboState() async => TurboState.fromJson(await call('turbo_state'));
  Future<TurboSet> turboSet(bool on) async => TurboSet.fromJson(await call('turbo_set', {'on': on}, false));

  Future<Uint8List?> thumbnail(int id) {
    if (_thumbs.containsKey(id)) {
      final v = _thumbs.remove(id);
      _thumbs[id] = v; // most recently used last
      return Future.value(v);
    }
    return _thumbsInFlight[id] ??= () async {
      Uint8List? bytes;
      try {
        final r = await call('thumbnail', {'id': id});
        bytes = decodeImageDataUrl(r is Map ? r['url'] : null);
      } on EngineOffline {
        return null; // not cached: try again when it's back
      } catch (_) {
        bytes = null;
      } finally {
        _thumbsInFlight.remove(id);
      }
      _thumbs[id] = bytes;
      while (_thumbs.length > _thumbCache) {
        _thumbs.remove(_thumbs.keys.first);
      }
      return bytes;
    }();
  }

  void dispose() {
    _disposed = true;
    _rpc?.close();
    _events.close();
    _link.dispose();
  }
}

/// What the 2026-11-18 prototype engine serves (its hello has no `methods` list).
const prototypeMethods = {'hello', 'subscribe', 'search', 'open', 'reveal', 'thumbnail', 'status'};

/// `data:image/png;base64,....` (from thumbs.py) -> the image bytes, or null for anything else.
Uint8List? decodeImageDataUrl(Object? url) {
  if (url is! String || url.length > 2 * maxMessage) return null;
  final m = RegExp(r'^data:image/(png|jpeg|bmp);base64,').firstMatch(url);
  if (m == null) return null;
  try {
    final bytes = base64Decode(url.substring(m.end));
    return bytes.isEmpty ? null : bytes;
  } on FormatException {
    return null;
  }
}

/// Bytes -> lines, at most [cap] bytes each (a longer one ends the connection: [LineTooLong]).
class LineSplitterBytes {
  LineSplitterBytes({this.cap = maxMessage});
  final int cap;
  final _buf = BytesBuilder(copy: false);
  Uint8List _rest = Uint8List(0);

  List<String> feed(Uint8List data) {
    final out = <String>[];
    var bytes = data;
    if (_rest.isNotEmpty) {
      _buf
        ..add(_rest)
        ..add(data);
      bytes = _buf.takeBytes();
    }
    var start = 0;
    for (var i = 0; i < bytes.length; i++) {
      if (bytes[i] == 0x0A) {
        var end = i;
        if (end > start && bytes[end - 1] == 0x0D) end--;
        if (end - start > cap) throw const LineTooLong();
        if (end > start) out.add(utf8.decode(Uint8List.sublistView(bytes, start, end), allowMalformed: true));
        start = i + 1;
      }
    }
    _rest = Uint8List.fromList(Uint8List.sublistView(bytes, start));
    if (_rest.length > cap) throw const LineTooLong();
    return out;
  }
}

class LineTooLong implements Exception {
  const LineTooLong();
}
