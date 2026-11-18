/// The few window moves the UI makes itself (user32 through dart:ffi; no window plugin needed).
///
/// The runner (windows/runner/main.cpp) makes the bar window frameless, on top and placed before its first frame;
/// this file hides it, shows it again on the monitor with the mouse, grows it to the result rows, and brings the
/// main window to the front. Calls that move or show the window are asynchronous (SWP_ASYNCWINDOWPOS,
/// ShowWindowAsync) so the UI thread never waits on the window's thread.
library;

import 'dart:ffi';
import 'dart:io' show Platform;

import 'package:ffi/ffi.dart';

abstract class WindowControl {
  void hide();
  void showBar();
  void fitBar(int rows);
  void front();
}

/// Tests and non-Windows: does nothing.
class NoWindow implements WindowControl {
  const NoWindow();
  @override
  void hide() {}
  @override
  void showBar() {}
  @override
  void fitBar(int rows) {}
  @override
  void front() {}
}

/// Bar geometry in logical pixels, the same as bar.py (WIDTH, HEIGHT, ROW, MAX_ROWS).
abstract final class BarSize {
  static const width = 640;
  static const field = 64;
  static const row = 44;
  static const maxRows = 8;

  /// Window height for [rows] result rows (one more pixel for the line above the list).
  static int height(int rows) => rows <= 0 ? field : field + 1 + rows.clamp(0, maxRows) * row;

  /// Top-left for a window of w x h in the work area: centered, a third of the way down (bar.place).
  static (int, int) place(int left, int top, int right, int bottom, int w, int h) =>
      (left + (right - left - w) ~/ 2, top + (bottom - top) ~/ 3 - h ~/ 2);
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
  static final _windowPid = _u32.lookupFunction<Uint32 Function(IntPtr, Pointer<Uint32>),
      int Function(int, Pointer<Uint32>)>('GetWindowThreadProcessId');
  static final _pid = _k32.lookupFunction<Uint32 Function(), int Function()>('GetCurrentProcessId');
  static final _showAsync =
      _u32.lookupFunction<Int32 Function(IntPtr, Int32), int Function(int, int)>('ShowWindowAsync');
  static final _setPos = _u32.lookupFunction<Int32 Function(IntPtr, IntPtr, Int32, Int32, Int32, Int32, Uint32),
      int Function(int, int, int, int, int, int, int)>('SetWindowPos');
  static final _dpiForWindow = _u32.lookupFunction<Uint32 Function(IntPtr), int Function(int)>('GetDpiForWindow');
  static final _cursor =
      _u32.lookupFunction<Int32 Function(Pointer<_POINT>), int Function(Pointer<_POINT>)>('GetCursorPos');
  static final _monitorFromPoint =
      _u32.lookupFunction<IntPtr Function(_POINT, Uint32), int Function(_POINT, int)>('MonitorFromPoint');
  static final _monitorInfo = _u32.lookupFunction<Int32 Function(IntPtr, Pointer<_MONITORINFO>),
      int Function(int, Pointer<_MONITORINFO>)>('GetMonitorInfoW');
  static final _dpiForMonitor = _shcore.lookupFunction<Int32 Function(IntPtr, Int32, Pointer<Uint32>, Pointer<Uint32>),
      int Function(int, int, Pointer<Uint32>, Pointer<Uint32>)>('GetDpiForMonitor');
  static final _setForeground =
      _u32.lookupFunction<Int32 Function(IntPtr), int Function(int)>('SetForegroundWindow');

  static const _swHide = 0, _swRestore = 9;
  static const _noSize = 0x1, _noMove = 0x2, _noZOrder = 0x4, _noActivate = 0x10, _showWindow = 0x40;
  static const _async = 0x4000;
  static const _topmost = -1;

  int _hwnd = 0;

  /// This process's top-level Flutter window (the runner's window class).
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

  double get _scale {
    final dpi = hwnd == 0 ? 96 : _dpiForWindow(hwnd);
    return (dpi == 0 ? 96 : dpi) / 96;
  }

  @override
  void hide() {
    if (hwnd != 0) _showAsync(hwnd, _swHide);
  }

  @override
  void fitBar(int rows) {
    if (hwnd == 0) return;
    final s = _scale;
    _setPos(hwnd, 0, 0, 0, (BarSize.width * s).round(), (BarSize.height(rows) * s).round(),
        _noMove | _noZOrder | _noActivate | _async);
  }

  @override
  void showBar() {
    if (hwnd == 0) return;
    using((arena) {
      final pt = arena<_POINT>();
      _cursor(pt);
      final mon = _monitorFromPoint(pt.ref, 2); // MONITOR_DEFAULTTONEAREST
      final info = arena<_MONITORINFO>()..ref.cbSize = sizeOf<_MONITORINFO>();
      final dx = arena<Uint32>(), dy = arena<Uint32>();
      var scale = 1.0;
      if (mon != 0 && _dpiForMonitor(mon, 0, dx, dy) == 0 && dx.value != 0) scale = dx.value / 96;
      final (l, t, r, b) = mon != 0 && _monitorInfo(mon, info) != 0
          ? (info.ref.rcWork.left, info.ref.rcWork.top, info.ref.rcWork.right, info.ref.rcWork.bottom)
          : (0, 0, 1920, 1040);
      final w = (BarSize.width * scale).round(), h = (BarSize.field * scale).round();
      final (x, y) = BarSize.place(l, t, r, b, w, h);
      _setPos(hwnd, _topmost, x, y, w, h, _showWindow | _async);
    });
    _setForeground(hwnd); // allowed: the engine passed on its hotkey's right to take the front
  }

  @override
  void front() {
    if (hwnd == 0) return;
    _showAsync(hwnd, _swRestore);
    _setPos(hwnd, 0, 0, 0, 0, 0, _noMove | _noSize | _noZOrder | _showWindow | _async);
    _setForeground(hwnd);
  }

}
