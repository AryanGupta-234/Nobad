/// The window's look on Windows 11: dark or light title bar, and Mica glass behind the window (DWM, dart:ffi).
///
/// Glass is drawn by Windows itself (the system backdrop), so it costs this process next to nothing; with the
/// setting off, or on Windows 10, the window is solid and the title bar takes the canvas colour.
library;

import 'dart:ffi';
import 'dart:io' show Platform;

import 'package:ffi/ffi.dart';

final class _MARGINS extends Struct {
  @Int32()
  external int left;
  @Int32()
  external int right;
  @Int32()
  external int top;
  @Int32()
  external int bottom;
}

abstract final class WindowLook {
  static const _darkMode = 20; // DWMWA_USE_IMMERSIVE_DARK_MODE
  static const _captionColor = 35; // DWMWA_CAPTION_COLOR
  static const _backdrop = 38; // DWMWA_SYSTEMBACKDROP_TYPE
  static const _backdropNone = 1, _backdropMica = 2;
  static const _colorDefault = 0xFFFFFFFF;

  static int Function(int, int, Pointer<Void>, int)? _set;
  static int Function(int, Pointer<_MARGINS>)? _extend;

  static bool _load() {
    if (!Platform.isWindows) return false;
    if (_set != null) return true;
    try {
      final dwm = DynamicLibrary.open('dwmapi.dll');
      _set = dwm
          .lookupFunction<
            Int32 Function(IntPtr, Uint32, Pointer<Void>, Uint32),
            int Function(int, int, Pointer<Void>, int)
          >('DwmSetWindowAttribute');
      _extend = dwm.lookupFunction<Int32 Function(IntPtr, Pointer<_MARGINS>), int Function(int, Pointer<_MARGINS>)>(
        'DwmExtendFrameIntoClientArea',
      );
      return true;
    } on Object {
      return false;
    }
  }

  /// Applies the theme to [hwnd]. Returns true when Windows took the glass (so the UI may draw see-through).
  static bool apply(int hwnd, {required bool dark, required bool glass, required int canvasRgb}) {
    if (hwnd == 0 || !_load()) return false;
    return using((a) {
      final v = a<Uint32>();
      v.value = dark ? 1 : 0;
      _set!(hwnd, _darkMode, v.cast(), 4);
      v.value = glass ? _backdropMica : _backdropNone;
      final tookGlass = _set!(hwnd, _backdrop, v.cast(), 4) == 0 && glass; // fails before Windows 11 22H2
      final m = a<_MARGINS>();
      final e = tookGlass ? -1 : 0;
      m.ref
        ..left = e
        ..right = e
        ..top = e
        ..bottom = e;
      _extend!(hwnd, m);
      // COLORREF is 0x00BBGGRR.
      final r = (canvasRgb >> 16) & 0xFF, g = (canvasRgb >> 8) & 0xFF, b = canvasRgb & 0xFF;
      v.value = tookGlass ? _colorDefault : (b << 16) | (g << 8) | r;
      _set!(hwnd, _captionColor, v.cast(), 4);
      return tookGlass;
    });
  }
}
