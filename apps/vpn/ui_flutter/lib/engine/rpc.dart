/// JSON-RPC 2.0 to the engine: request ids, timeouts, events, and reconnecting with backoff.
/// Adapted from NOBAD Find (apps/find/ui_flutter/lib/engine/rpc.dart).
///
/// The transport (the named pipe, or a fake in tests) only moves lines; everything about the protocol is here.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';

const protocolVersion = 1;
const maxMessage = 1024 * 1024;

enum Link { connecting, connected, offline, incompatible, refused }

/// The engine answered with a JSON-RPC error; [message] is plain language.
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
  @override
  String toString() => "NOBAD VPN isn't running.";
}

/// An event the engine pushed: `{method: name, params}`.
class EngineEvent {
  const EngineEvent(this.name, this.params);
  final String name;
  final Object? params;
  Map<String, Object?> get map => params is Map ? Map<String, Object?>.from(params as Map) : const {};
}

/// The events every window wants (contract/README.md, "Start-up order").
const mainEvents = [
  'state', 'traffic', 'health', 'direct_health', 'probe', 'log', 'error_action', 'notify', 'fix_result',
  'task_done', 'ipinfo', 'endpoint_report', 'net_repair_start', 'net_repair_done', 'update', 'show', 'quitting',
];
const miniEvents = ['state', 'traffic', 'error_action', 'show', 'quitting'];

abstract class Transport {
  Stream<String> get lines;
  void send(String line);
  Future<void> close();
}

typedef Connector = Future<Transport> Function();

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
      timeout ?? const Duration(seconds: 20),
      onTimeout: () {
        _pending.remove(id);
        throw const RpcException(-32000, 'NOBAD VPN took too long to answer.');
      },
    );
  }

  void _line(String line) {
    Object? msg;
    try {
      msg = jsonDecode(line);
    } catch (_) {
      return;
    }
    if (msg is! Map) return;
    final id = msg['id'];
    if (id is int && _pending.containsKey(id)) {
      final c = _pending.remove(id)!;
      final err = msg['error'];
      if (err is Map) {
        c.completeError(
          RpcException(err['code'] is int ? err['code'] as int : -32603,
              err['message'] is String ? err['message'] as String : 'Error'),
        );
      } else {
        c.complete(msg['result']);
      }
      return;
    }
    if (msg.containsKey('id') && msg['id'] == null && msg['error'] is Map) {
      // an error for no request in particular: the engine refused this program, or a line was too big
      final err = msg['error'] as Map;
      final e = RpcException(err['code'] is int ? err['code'] as int : -32700,
          err['message'] is String ? err['message'] as String : 'NOBAD VPN could not read a request.');
      for (final c in _pending.values) {
        c.completeError(e);
      }
      _pending.clear();
      return;
    }
    final method = msg['method'];
    if (method is String && !msg.containsKey('id')) _onEvent(EngineEvent(method, msg['params']));
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

/// The real engine over the pipe: the connection, its events, and [call] for any contract method.
class EngineClient {
  EngineClient(this._connect, {List<Duration>? backoff, this.log, this.subscribeTo = mainEvents, this.window = 'main'})
    : _backoff = backoff ??
          const [
            Duration(milliseconds: 250),
            Duration(milliseconds: 500),
            Duration(seconds: 1),
            Duration(seconds: 2),
            Duration(seconds: 4),
          ];

  final Connector _connect;
  final List<Duration> _backoff;
  final void Function(String)? log;
  final List<String> subscribeTo;
  final String window;
  final _link = ValueNotifier(Link.connecting);
  final _events = StreamController<EngineEvent>.broadcast();
  RpcSession? _rpc;
  var _disposed = false, _started = false, _quitting = false;
  /// Both windows start on screen (the runner shows them); the engine is told on every (re)connect.
  bool _shown = true;

  /// What the connected engine serves (`hello.methods`), its version and its pid.
  Set<String> served = const {};
  String engineVersion = '';
  int enginePid = 0;

  ValueListenable<Link> get link => _link;
  Stream<EngineEvent> get events => _events.stream;
  bool get quitting => _quitting;

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
        if (h['protocol'] != protocolVersion) {
          log?.call('engine speaks protocol ${h['protocol']}, this window $protocolVersion');
          _link.value = Link.incompatible;
          await rpc.close();
          await Future<void>.delayed(const Duration(seconds: 10));
          continue;
        }
        final methods = h['methods'];
        served = methods is List ? {for (final m in methods) if (m is String) m} : const {};
        engineVersion = h['version'] is String ? h['version'] as String : '';
        enginePid = h['pid'] is int ? h['pid'] as int : 0;
        await rpc.call('subscribe', {'events': subscribeTo});
        _rpc = rpc;
        attempt = 0;
        _link.value = Link.connected;
        unawaited(rpc.call('state').then((s) => _event(EngineEvent('state', s)), onError: (_) {}));
        unawaited(
          rpc.call(_shown ? 'ui_shown' : 'ui_hidden', {'window': window}).then((_) {}, onError: (_) {}),
        );
        await rpc.done;
      } on RpcException catch (e) {
        log?.call('engine refused: ${e.message}');
        await rpc?.close();
        if (e.code == -32001) {
          _link.value = Link.refused; // this program may not control NOBAD VPN: don't hammer the pipe
          await Future<void>.delayed(const Duration(seconds: 15));
          continue;
        }
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
    if (e.name == 'quitting') _quitting = true;
    if (!_events.isClosed) _events.add(e);
  }

  /// Any method by name. EngineOffline when not connected; RpcException for a protocol error.
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) {
    final rpc = _rpc;
    if (rpc == null || !rpc.isOpen) return Future.error(const EngineOffline());
    if (served.isNotEmpty && !served.contains(method)) {
      return Future.error(const RpcException(-32601, "This version of NOBAD VPN can't do that yet. Update it."));
    }
    return rpc.call(method, params);
  }

  /// The window came on screen or went away: the engine samples faster only while one is visible.
  Future<void> shown(bool on) {
    _shown = on;
    final rpc = _rpc;
    if (rpc == null || !rpc.isOpen) return Future.value();
    return rpc.call(on ? 'ui_shown' : 'ui_hidden', {'window': window}).then((_) {}, onError: (_) {});
  }

  void dispose() {
    _disposed = true;
    _rpc?.close();
    _events.close();
    _link.dispose();
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
