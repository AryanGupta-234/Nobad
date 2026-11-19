/// The few window moves the UI makes itself (user32 through dart:ffi; no window plugin). Adapted from NOBAD Find.
///
/// The runner (windows/runner/main.cpp) makes the pop-up frameless, on top and placed next to the tray before its
/// first frame; this file hides it, shows it again next to the tray, brings the main window to the front, and
/// starts the other window's process (this same program, at this user's normal rights) when no copy is running.
library;

import 'dart:async';
import 'dart:ffi';
import 'dart:io' show Platform, Process, ProcessStartMode;

import 'package:ffi/ffi.dart';
import 'package:flutter/services.dart' show SystemChannels;

import '../app/theme/glass.dart';

abstract class WindowControl {
  void hide();
  void showMini();
  void front();
  bool look({required bool dark, required bool glass, required int canvasRgb});
  void close();

  /// Start the other window's process ("main" or "mini"). False if it couldn't.
  bool spawn(String window);
  int get handle;
}

class NoWindow implements WindowControl {
  const NoWindow();
  @override
  void hide() {}
  @override
  void showMini() {}
  @override
  void front() {}
  @override
  bool look({required bool dark, required bool glass, required int canvasRgb}) => false;
  @override
  void close() {}
  @override
  bool spawn(String window) => false;
  @override
  int get handle => 0;
}

/// The pop-up's size in logical pixels (main.cpp kMiniWidth / kMiniHeight).
abstract final class MiniSize {
  static const width = 320;
  static const height = 392;
  static const gap = 12;

  /// Top-left for the pop-up next to the tray: the work-area corner on the taskbar's side.
  /// (l, t, r, b) work area; (ml, mt) the monitor's top-left.
  static (int, int) place(int l, int t, int r, int b, int ml, int mt, int w, int h, int g) {
    var x = r - w - g, y = b - h - g;
    if (t > mt) {
      y = t + g; // taskbar on top
    } else if (l > ml) {
      x = l + g; // taskbar on the left
    }
    return (x, y);
  }
}

final class _POINT extends Struct {
  @Int32()
  external int x;
  @Int32()
  external int y;
}

final class _RECT extends Struct {
  @Int32()
  external int left;
  @Int32()
  external int top;
  @Int32()
  external int right;
  @Int32()
  external int bottom;
}

final class _MONITORINFO extends Struct {
  @Uint32()
  external int cbSize;
  external _RECT rcMonitor;
  external _RECT rcWork;
  @Uint32()
  external int dwFlags;
}

class Win32Window implements WindowControl {
  Win32Window._();

  static WindowControl create() => Platform.isWindows ? Win32Window._() : const NoWindow();

  static final _u32 = DynamicLibrary.open('user32.dll');
  static final _k32 = DynamicLibrary.open('kernel32.dll');
  static final _shcore = DynamicLibrary.open('shcore.dll');
  static final _findWindowEx = _u32.lookupFunction<IntPtr Function(IntPtr, IntPtr, Pointer<Utf16>, Pointer<Utf16>),
      int Function(int, int, Pointer<Utf16>, Pointer<Utf16>)>('FindWindowExW');
  static final _windowPid = _u32
      .lookupFunction<Uint32 Function(IntPtr, Pointer<Uint32>), int Function(int, Pointer<Uint32>)>('GetWindowThreadProcessId');
  static final _pid = _k32.lookupFunction<Uint32 Function(), int Function()>('GetCurrentProcessId');
  static final _showAsync = _u32.lookupFunction<Int32 Function(IntPtr, Int32), int Function(int, int)>('ShowWindowAsync');
  static final _setPos = _u32.lookupFunction<Int32 Function(IntPtr, IntPtr, Int32, Int32, Int32, Int32, Uint32),
      int Function(int, int, int, int, int, int, int)>('SetWindowPos');
  static final _cursor = _u32.lookupFunction<Int32 Function(Pointer<_POINT>), int Function(Pointer<_POINT>)>('GetCursorPos');
  static final _monitorFromPoint =
      _u32.lookupFunction<IntPtr Function(_POINT, Uint32), int Function(_POINT, int)>('MonitorFromPoint');
  static final _monitorInfo = _u32.lookupFunction<Int32 Function(IntPtr, Pointer<_MONITORINFO>),
      int Function(int, Pointer<_MONITORINFO>)>('GetMonitorInfoW');
  static final _dpiForMonitor = _shcore.lookupFunction<Int32 Function(IntPtr, Int32, Pointer<Uint32>, Pointer<Uint32>),
      int Function(int, int, Pointer<Uint32>, Pointer<Uint32>)>('GetDpiForMonitor');
  static final _setForeground = _u32.lookupFunction<Int32 Function(IntPtr), int Function(int)>('SetForegroundWindow');
  static final _currentProcess = _k32.lookupFunction<IntPtr Function(), int Function()>('GetCurrentProcess');
  static final _emptyWorkingSet = _k32.lookupFunction<Int32 Function(IntPtr), int Function(int)>('K32EmptyWorkingSet');
  static final _postMessage = _u32
      .lookupFunction<Int32 Function(IntPtr, Uint32, IntPtr, IntPtr), int Function(int, int, int, int)>('PostMessageW');

  static const _swHide = 0, _swRestore = 9;
  static const _noSize = 0x1, _noMove = 0x2, _noZOrder = 0x4, _showWindow = 0x40, _async = 0x4000;
  static const _topmost = -1;

  /// Skia's GPU cache while shown (main.dart sets it at start); hidden, it's emptied.
  static int shownCacheBytes = 12 << 20;

  /// The tray pop-up: Acrylic and round corners (main.dart sets it for --mini).
  static bool acrylic = false;

  int _hwnd = 0;

  int get hwnd {
    if (_hwnd != 0) return _hwnd;
    final cls = 'FLUTTER_RUNNER_WIN32_WINDOW'.toNativeUtf16();
    final pid = calloc<Uint32>();
    try {
      final me = _pid();
      var h = 0;
      while ((h = _findWindowEx(0, h, cls, nullptr)) != 0) {
        _windowPid(h, pid);
        if (pid.value == me) return _hwnd = h;
      }
      return 0;
    } finally {
      calloc.free(cls);
      calloc.free(pid);
    }
  }

  static void _gpuCache(int bytes) =>
      SystemChannels.skia.invokeMethod<void>('Skia.setResourceCacheMaxBytes', bytes).catchError((Object _) {});

  /// Hide, then hand this process's working set back to Windows: a hidden window needs next to no RAM.
  @override
  void hide() {
    if (hwnd == 0) return;
    _showAsync(hwnd, _swHide);
    _gpuCache(0);
    Future<void>.delayed(const Duration(milliseconds: 120), () => _gpuCache(shownCacheBytes));
    Future<void>.delayed(const Duration(milliseconds: 300), () => _emptyWorkingSet(_currentProcess()));
  }

  @override
  void showMini() {
    if (hwnd == 0) return;
    using((arena) {
      final pt = arena<_POINT>();
      _cursor(pt);
      final mon = _monitorFromPoint(pt.ref, 2);
      final info = arena<_MONITORINFO>()..ref.cbSize = sizeOf<_MONITORINFO>();
      final dx = arena<Uint32>(), dy = arena<Uint32>();
      var scale = 1.0;
      if (mon != 0 && _dpiForMonitor(mon, 0, dx, dy) == 0 && dx.value != 0) scale = dx.value / 96;
      if (mon == 0 || _monitorInfo(mon, info) == 0) return;
      final w = info.ref.rcWork, m = info.ref.rcMonitor;
      final pw = (MiniSize.width * scale).round(), ph = (MiniSize.height * scale).round();
      final (x, y) = MiniSize.place(w.left, w.top, w.right, w.bottom, m.left, m.top, pw, ph, (MiniSize.gap * scale).round());
      _setPos(hwnd, _topmost, x, y, pw, ph, _showWindow | _async);
    });
    _setForeground(hwnd);
  }

  @override
  void front() {
    if (hwnd == 0) return;
    _showAsync(hwnd, _swRestore);
    _setPos(hwnd, 0, 0, 0, 0, 0, _noMove | _noSize | _noZOrder | _showWindow | _async);
    _setForeground(hwnd);
  }

  @override
  bool look({required bool dark, required bool glass, required int canvasRgb}) =>
      WindowLook.apply(hwnd, dark: dark, glass: glass, canvasRgb: canvasRgb, acrylic: acrylic);

  @override
  void close() {
    if (hwnd != 0) _postMessage(hwnd, 0x0010, 0, 0); // WM_CLOSE: the runner quits when its window closes
  }

  /// This same program for the other window, detached, at this process's (normal) rights. Its single-instance
  /// mutex makes a second copy hand over to the first.
  @override
  bool spawn(String window) {
    allowSetForeground(-1); // ASFW_ANY: the new window may take the front from us
    try {
      unawaited(Process.start(Platform.resolvedExecutable, window == 'mini' ? const ['--mini'] : const [],
          mode: ProcessStartMode.detached));
      return true;
    } on Object {
      return false;
    }
  }

  @override
  int get handle => hwnd;
}

/// Let another process (the engine's dialog, the other window) bring its window to the front. -1: any.
void allowSetForeground(int pid) {
  if (!Platform.isWindows || pid == 0) return;
  try {
    final u32 = DynamicLibrary.open('user32.dll');
    u32.lookupFunction<Int32 Function(Uint32), int Function(int)>('AllowSetForegroundWindow')(pid & 0xFFFFFFFF);
  } on Object {
    // best effort
  }
}

/// Windows' Settings > Accessibility > Visual effects > "Animation effects" is off.
bool systemAnimationsOff() {
  if (!Platform.isWindows) return false;
  try {
    final u32 = DynamicLibrary.open('user32.dll');
    final spi = u32.lookupFunction<Int32 Function(Uint32, Uint32, Pointer<Int32>, Uint32),
        int Function(int, int, Pointer<Int32>, int)>('SystemParametersInfoW');
    return using((a) {
      final v = a<Int32>();
      if (spi(0x1042, 0, v, 0) == 0) return false; // SPI_GETCLIENTAREAANIMATION
      return v.value == 0;
    });
  } on Object {
    return false;
  }
}
