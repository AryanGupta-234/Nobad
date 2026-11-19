/// The Windows named pipe to the NOBAD VPN engine: `\\.\pipe\NOBADVPN-<user SID>` (dart:ffi, overlapped I/O).
/// Adapted from NOBAD Find (apps/find/ui_flutter/lib/engine/pipe_client.dart).
///
/// - Connects with identification-level impersonation only (SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION): the
///   engine can check who this is (contract/README.md, "Who may connect"), but can't act as this user.
/// - Checks the pipe's owner before sending anything: it must be Administrators or SYSTEM, i.e. made by an elevated
///   process. A program running as this user that took the name first can't pose as the engine and show a false
///   "Protected". The development engine (NOBAD_VPN_DEV_ENGINE=1, unelevated, for screenshots) has its own pipe
///   name, owned by this user.
/// - Reads in a small background isolate, writes from the UI isolate. Lines are capped at [maxMessage].
library;

import 'dart:async';
import 'dart:convert';
import 'dart:ffi';
import 'dart:isolate';
import 'dart:typed_data';

import 'package:ffi/ffi.dart';

import 'rpc.dart';

// ---------- the few Win32 calls needed (kernel32, advapi32) ----------
final class _OVERLAPPED extends Struct {
  @IntPtr()
  external int internal;
  @IntPtr()
  external int internalHigh;
  @Uint32()
  external int offset;
  @Uint32()
  external int offsetHigh;
  @IntPtr()
  external int hEvent;
}

final _k32 = DynamicLibrary.open('kernel32.dll');
final _adv = DynamicLibrary.open('advapi32.dll');

final _createFile = _k32
    .lookupFunction<
      IntPtr Function(Pointer<Utf16>, Uint32, Uint32, Pointer<Void>, Uint32, Uint32, IntPtr),
      int Function(Pointer<Utf16>, int, int, Pointer<Void>, int, int, int)
    >('CreateFileW');
final _waitNamedPipe = _k32.lookupFunction<Int32 Function(Pointer<Utf16>, Uint32), int Function(Pointer<Utf16>, int)>(
  'WaitNamedPipeW',
);
final _readFile = _k32
    .lookupFunction<
      Int32 Function(IntPtr, Pointer<Uint8>, Uint32, Pointer<Uint32>, Pointer<_OVERLAPPED>),
      int Function(int, Pointer<Uint8>, int, Pointer<Uint32>, Pointer<_OVERLAPPED>)
    >('ReadFile');
final _writeFile = _k32
    .lookupFunction<
      Int32 Function(IntPtr, Pointer<Uint8>, Uint32, Pointer<Uint32>, Pointer<_OVERLAPPED>),
      int Function(int, Pointer<Uint8>, int, Pointer<Uint32>, Pointer<_OVERLAPPED>)
    >('WriteFile');
final _getOverlappedResult = _k32
    .lookupFunction<
      Int32 Function(IntPtr, Pointer<_OVERLAPPED>, Pointer<Uint32>, Int32),
      int Function(int, Pointer<_OVERLAPPED>, Pointer<Uint32>, int)
    >('GetOverlappedResult');
final _createEvent = _k32
    .lookupFunction<
      IntPtr Function(Pointer<Void>, Int32, Int32, Pointer<Utf16>),
      int Function(Pointer<Void>, int, int, Pointer<Utf16>)
    >('CreateEventW');
final _cancelIoEx = _k32
    .lookupFunction<Int32 Function(IntPtr, Pointer<_OVERLAPPED>), int Function(int, Pointer<_OVERLAPPED>)>(
      'CancelIoEx',
    );
final _closeHandle = _k32.lookupFunction<Int32 Function(IntPtr), int Function(int)>('CloseHandle');
final _localFree = _k32.lookupFunction<IntPtr Function(Pointer<Void>), int Function(Pointer<Void>)>('LocalFree');
final _getCurrentProcess = _k32.lookupFunction<IntPtr Function(), int Function()>('GetCurrentProcess');
final _openProcessToken = _adv
    .lookupFunction<Int32 Function(IntPtr, Uint32, Pointer<IntPtr>), int Function(int, int, Pointer<IntPtr>)>(
      'OpenProcessToken',
    );
final _getTokenInformation = _adv
    .lookupFunction<
      Int32 Function(IntPtr, Int32, Pointer<Void>, Uint32, Pointer<Uint32>),
      int Function(int, int, Pointer<Void>, int, Pointer<Uint32>)
    >('GetTokenInformation');
final _convertSidToStringSid = _adv
    .lookupFunction<
      Int32 Function(Pointer<Void>, Pointer<Pointer<Utf16>>),
      int Function(Pointer<Void>, Pointer<Pointer<Utf16>>)
    >('ConvertSidToStringSidW');
final _getSecurityInfo = _adv
    .lookupFunction<
      Uint32 Function(
        IntPtr,
        Int32,
        Uint32,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
      ),
      int Function(
        int,
        int,
        int,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
        Pointer<Pointer<Void>>,
      )
    >('GetSecurityInfo');

const _genericReadWrite = 0xC0000000;
const _openExisting = 3;
const _fileFlagOverlapped = 0x40000000;
const _securitySqosPresent = 0x00100000;
const _securityIdentification = 0x00010000;
const _invalidHandle = -1;
const _tokenQuery = 0x8;
const _tokenUser = 1;
const _seKernelObject = 6;
const _ownerSecurityInformation = 1;
const _bufSize = 64 * 1024;

/// Runs [body] with this process's user SID (a pointer valid only inside [body]).
T _withUserSid<T>(T Function(Pointer<Void> sid) body) {
  return using((arena) {
    final tok = arena<IntPtr>();
    if (_openProcessToken(_getCurrentProcess(), _tokenQuery, tok) == 0) {
      throw StateError('OpenProcessToken failed');
    }
    try {
      const size = 256; // TOKEN_USER + the largest SID fit easily
      final buf = arena<Uint8>(size);
      final got = arena<Uint32>();
      if (_getTokenInformation(tok.value, _tokenUser, buf.cast(), size, got) == 0) {
        throw StateError('GetTokenInformation failed');
      }
      return body(Pointer<Void>.fromAddress(buf.cast<IntPtr>().value)); // TOKEN_USER.User.Sid
    } finally {
      _closeHandle(tok.value);
    }
  });
}

/// The current user's SID as a string, e.g. S-1-5-21-…
String userSid() => _withUserSid((sid) {
  final out = calloc<Pointer<Utf16>>();
  try {
    if (_convertSidToStringSid(sid, out) == 0) throw StateError('ConvertSidToStringSid failed');
    final s = out.value.toDartString();
    _localFree(out.value.cast());
    return s;
  } finally {
    calloc.free(out);
  }
});

/// The engine's pipe; [dev] the unelevated development engine's.
String enginePipeName({String? sid, bool dev = false}) =>
    r'\\.\pipe\NOBADVPN-' + (dev ? 'dev-' : '') + (sid ?? userSid());

const _admins = 'S-1-5-32-544', _system = 'S-1-5-18';

/// The pipe's owner as a string SID, or null.
String? _ownerOf(int handle) {
  final owner = calloc<Pointer<Void>>();
  final sd = calloc<Pointer<Void>>();
  final out = calloc<Pointer<Utf16>>();
  try {
    final err = _getSecurityInfo(handle, _seKernelObject, _ownerSecurityInformation, owner, nullptr, nullptr,
        nullptr, sd);
    if (err != 0 || owner.value == nullptr) return null;
    if (_convertSidToStringSid(owner.value, out) == 0) return null;
    final s = out.value.toDartString();
    _localFree(out.value.cast());
    return s;
  } finally {
    if (sd.value != nullptr) _localFree(sd.value);
    calloc.free(owner);
    calloc.free(sd);
    calloc.free(out);
  }
}

/// Who may own the pipe: an elevated process (Administrators / SYSTEM); for the dev engine, this user.
bool ownerAllowed(String? owner, {required bool dev, required String me}) =>
    owner != null && (dev ? owner == me : (owner == _admins || owner == _system));

class PipeNotOwned implements Exception {
  const PipeNotOwned();
  @override
  String toString() => "NOBAD VPN's pipe wasn't made by NOBAD VPN; not connecting.";
}

/// A connected pipe. [connect] fails fast (EngineOffline) when no engine is listening.
class PipeTransport implements Transport {
  PipeTransport._(this._handle) {
    _wov.ref.hEvent = _createEvent(nullptr, 1, 0, nullptr);
  }

  /// [dev]: the unelevated development engine (NOBAD_VPN_DEV_ENGINE=1).
  static Future<Transport> connect({String? name, bool dev = false}) async {
    final path = (name ?? enginePipeName(dev: dev)).toNativeUtf16();
    try {
      var h = _open(path);
      if (h == _invalidHandle && _waitNamedPipe(path, 1000) != 0) {
        h = _open(path); // every instance was busy a moment ago
      }
      if (h == _invalidHandle) throw const EngineOffline();
      if (!ownerAllowed(_ownerOf(h), dev: dev, me: userSid())) {
        _closeHandle(h);
        throw const PipeNotOwned();
      }
      final t = PipeTransport._(h);
      await t._startReader();
      return t;
    } finally {
      calloc.free(path);
    }
  }

  static int _open(Pointer<Utf16> path) => _createFile(
    path,
    _genericReadWrite,
    0,
    nullptr,
    _openExisting,
    _fileFlagOverlapped | _securitySqosPresent | _securityIdentification,
    0,
  );

  final int _handle;
  final _wov = calloc<_OVERLAPPED>();
  final _written = calloc<Uint32>();
  final _lines = StreamController<String>();
  final _split = LineSplitterBytes();
  ReceivePort? _port;
  var _readerDone = false;
  var _closed = false;

  /// Set by close(); the reader isolate checks it before every read (a cancel between two reads finds nothing to
  /// cancel). Shared native memory, freed once the reader is done.
  final _stop = calloc<Int32>();
  Timer? _forceClose;

  @override
  Stream<String> get lines => _lines.stream;

  Future<void> _startReader() async {
    final port = _port = ReceivePort();
    port.listen((msg) {
      if (msg is TransferableTypedData) {
        try {
          for (final line in _split.feed(msg.materialize().asUint8List())) {
            _lines.add(line);
          }
        } on LineTooLong {
          close();
        }
      } else {
        _readerDone = true; // the pipe broke, or close() cancelled the read
        close();
      }
    });
    try {
      await Isolate.spawn(_readLoop, (_handle, port.sendPort, _stop.address), debugName: 'engine-pipe-reader');
    } on Object {
      _readerDone = true; // no reader: nothing else will release the handle
      _closed = true;
      _release();
      rethrow;
    }
  }

  @override
  void send(String line) {
    if (_closed) throw const EngineOffline();
    final bytes = utf8.encode('$line\n');
    if (bytes.length > maxMessage) throw const RpcException(-32600, 'Request too big');
    final buf = calloc<Uint8>(bytes.length);
    try {
      buf.asTypedList(bytes.length).setAll(0, bytes);
      _wov.ref
        ..internal = 0
        ..internalHigh = 0;
      _writeFile(_handle, buf, bytes.length, nullptr, _wov);
      // Small writes into the engine's 64 KB pipe buffer finish at once; the engine always reads.
      if (_getOverlappedResult(_handle, _wov, _written, 1) == 0 || _written.value != bytes.length) {
        close();
        throw const EngineOffline();
      }
    } finally {
      calloc.free(buf);
    }
  }

  @override
  Future<void> close() async {
    if (_closed) {
      if (_readerDone) _release();
      return;
    }
    _closed = true;
    _stop.value = 1;
    _cancelIoEx(_handle, nullptr); // wakes the reader isolate, which then reports done
    if (_readerDone) {
      _release();
    } else {
      // a read that started just after the cancel would wait forever: closing the handle ends it
      _forceClose = Timer(const Duration(milliseconds: 500), () {
        if (_readerDone) return;
        _cancelIoEx(_handle, nullptr);
        _closeHandleOnce();
      });
    }
    if (!_lines.isClosed) await _lines.close();
  }

  var _released = false;
  var _handleClosed = false;
  void _closeHandleOnce() {
    if (_handleClosed) return;
    _handleClosed = true;
    _closeHandle(_handle);
  }

  void _release() {
    if (_released) return;
    _released = true;
    _forceClose?.cancel();
    _port?.close();
    _closeHandleOnce();
    _closeHandle(_wov.ref.hEvent);
    calloc.free(_wov);
    calloc.free(_written);
    calloc.free(_stop);
  }
}

/// The reader isolate: overlapped ReadFile + wait, forever, sending each chunk back. Ends on any failure or a
/// zero-byte read (the pipe closed, or the UI cancelled the read to disconnect).
void _readLoop((int, SendPort, int) args) {
  final (handle, port, stopAddress) = args;
  final stop = Pointer<Int32>.fromAddress(stopAddress);
  final ov = calloc<_OVERLAPPED>();
  final buf = calloc<Uint8>(_bufSize);
  final got = calloc<Uint32>();
  ov.ref.hEvent = _createEvent(nullptr, 1, 0, nullptr);
  try {
    while (stop.value == 0) {
      ov.ref
        ..internal = 0
        ..internalHigh = 0;
      _readFile(handle, buf, _bufSize, nullptr, ov);
      // An immediate failure leaves Internal at 0 and 0 bytes: treated as the end, no GetLastError needed.
      if (_getOverlappedResult(handle, ov, got, 1) == 0 || got.value == 0) break;
      port.send(TransferableTypedData.fromList([Uint8List.fromList(buf.asTypedList(got.value))]));
    }
  } finally {
    _closeHandle(ov.ref.hEvent);
    calloc.free(ov);
    calloc.free(buf);
    calloc.free(got);
    port.send(null);
  }
}
