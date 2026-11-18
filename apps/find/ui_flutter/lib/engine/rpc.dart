/// JSON-RPC 2.0 to the engine: request ids, timeouts, typed calls, events, and reconnecting with backoff.
///
/// The transport (the named pipe, or a fake in tests) only moves lines; everything about the protocol is here.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';

import 'events.dart';
import 'models/result.dart';
import 'models/status.dart';

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

class RpcException implements Exception {
  const RpcException(this.code, this.message);
  final int code;
  final String message;
  @override
  String toString() => 'RpcException($code, $message)';
}

class EngineOffline implements Exception {
  const EngineOffline();
}

/// One connection's request/response bookkeeping.
class RpcSession {
  RpcSession(this._t, {required void Function(EngineEvent) onEvent}) : _onEvent = onEvent {  // ignore: prefer_initializing_formals
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
    final c = Completer<Object?>();
    _pending[id] = c;
    final line = jsonEncode({'jsonrpc': '2.0', 'id': id, 'method': method, 'params': params});
    try {
      _t.send(line);
    } catch (_) {
      _pending.remove(id);
      _closed();
      return Future.error(const EngineOffline());
    }
    return c.future.timeout(timeout ?? const Duration(seconds: 15), onTimeout: () {
      _pending.remove(id);
      throw const RpcException(-32000, 'The engine took too long to answer.');
    });
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
        c.completeError(RpcException(err['code'] is int ? err['code'] as int : -32603,
            err['message'] is String ? err['message'] as String : 'Error'));
      } else {
        c.complete(msg['result']);
      }
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

enum Link { connecting, connected, offline, incompatible }

/// What the screens' controllers need from the engine. EngineClient is the real one; tests use a fake.
abstract class Engine {
  ValueListenable<Link> get link;
  Stream<EngineEvent> get events;
  EngineStatus? get lastStatus;
  Future<SearchAnswer> search(String text, {Map<String, Object?> filters = const {}});
  Future<bool> open(int id);
  Future<bool> reveal(int id);

  /// A small preview (PNG/JPEG/BMP bytes) from Windows' thumbnail cache, or null.
  Future<Uint8List?> thumbnail(int id);
  void dispose();
}

class EngineClient implements Engine {
  EngineClient(this._connect, {List<Duration>? backoff, this.log})
      : _backoff = backoff ??
            const [
              Duration(milliseconds: 200), Duration(milliseconds: 500), Duration(seconds: 1),
              Duration(seconds: 2), Duration(seconds: 4),
            ];

  final Connector _connect;
  final List<Duration> _backoff;
  final void Function(String)? log;
  final _link = ValueNotifier(Link.connecting);
  final _events = StreamController<EngineEvent>.broadcast();
  final _thumbs = <int, Uint8List?>{}; // insertion-ordered: the first key is the least recently used
  final _thumbsInFlight = <int, Future<Uint8List?>>{};
  static const _thumbCache = 300;
  RpcSession? _rpc;
  EngineStatus? _last;
  var _disposed = false;
  var _started = false;

  @override
  ValueListenable<Link> get link => _link;
  @override
  Stream<EngineEvent> get events => _events.stream;
  @override
  EngineStatus? get lastStatus => _last;

  /// Connects now and keeps reconnecting (with backoff) for as long as the client lives.
  void start() {
    if (_started) return;
    _started = true;
    unawaited(_loop());
  }

  Future<void> _loop() async {
    var attempt = 0;
    while (!_disposed) {
      RpcSession? rpc;
      try {
        final t = await _connect();
        if (_disposed) {
          await t.close();
          return;
        }
        rpc = RpcSession(t, onEvent: _event);
        final hello = await rpc.call('hello', const {}, const Duration(seconds: 5));
        final v = hello is Map ? hello['protocol'] : null;
        if (v != protocolVersion) {
          log?.call('engine speaks protocol $v, this UI $protocolVersion');
          _link.value = Link.incompatible;
          await rpc.close();
          await Future<void>.delayed(const Duration(seconds: 10));
          continue;
        }
        await rpc.call('subscribe', const {'events': ['status', 'show']});
        _rpc = rpc;
        attempt = 0;
        _link.value = Link.connected;
        unawaited(rpc.call('status').then((s) => _event(StatusEvent(EngineStatus.fromJson(s))), onError: (_) {}));
        await rpc.done;
      } catch (e) {
        log?.call('engine connection: $e');
        await rpc?.close();
      }
      _rpc = null;
      if (_disposed) return;
      _link.value = Link.offline;
      await Future<void>.delayed(_backoff[attempt < _backoff.length ? attempt : _backoff.length - 1]);
      attempt++;
    }
  }

  void _event(EngineEvent e) {
    if (e is StatusEvent) _last = e.status;
    if (!_events.isClosed) _events.add(e);
  }

  Future<Object?> _call(String method, [Map<String, Object?> params = const {}]) {
    final rpc = _rpc;
    if (rpc == null || !rpc.isOpen) return Future.error(const EngineOffline());
    return rpc.call(method, params);
  }

  @override
  Future<SearchAnswer> search(String text, {Map<String, Object?> filters = const {}}) async =>
      SearchAnswer.fromJson(await _call('search', {'text': text, 'filters': filters}));

  @override
  Future<bool> open(int id) async {
    final r = await _call('open', {'id': id});
    return r is Map && r['ok'] == true;
  }

  @override
  Future<bool> reveal(int id) async {
    final r = await _call('reveal', {'id': id});
    return r is Map && r['ok'] == true;
  }

  @override
  Future<Uint8List?> thumbnail(int id) {
    if (_thumbs.containsKey(id)) {
      final v = _thumbs.remove(id);
      _thumbs[id] = v; // most recently used last
      return Future.value(v);
    }
    return _thumbsInFlight[id] ??= () async {
      Uint8List? bytes;
      try {
        final r = await _call('thumbnail', {'id': id});
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

  @override
  void dispose() {
    _disposed = true;
    _rpc?.close();
    _events.close();
    _link.dispose();
  }
}

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
