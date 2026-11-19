/// Which language focus Windows' own languages suggest (the engine's rule, `models.focus_from_languages`): any
/// Hindi display language or keyboard → "hindi", any other non-English one → "multilingual", else "english".
/// Read from Windows (GetUserDefaultUILanguage, GetKeyboardLayoutList); nothing leaves the PC.
library;

import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart';

/// 'english' | 'multilingual' | 'hindi', or null off Windows or if Windows can't say.
String? windowsLanguageFocus() {
  if (!Platform.isWindows) return null;
  try {
    final k32 = DynamicLibrary.open('kernel32.dll');
    final u32 = DynamicLibrary.open('user32.dll');
    final ui = k32.lookupFunction<Uint16 Function(), int Function()>('GetUserDefaultUILanguage');
    final layouts = u32.lookupFunction<Int32 Function(Int32, Pointer<IntPtr>), int Function(int, Pointer<IntPtr>)>(
      'GetKeyboardLayoutList',
    );
    final langs = <int>[ui()];
    using((a) {
      final n = layouts(0, nullptr);
      if (n <= 0 || n > 64) return;
      final list = a<IntPtr>(n);
      final got = layouts(n, list);
      for (var i = 0; i < got; i++) {
        langs.add(list[i] & 0xFFFF); // the low word is the input language
      }
    });
    return focusFromLangIds(langs);
  } on Object {
    return null;
  }
}

/// [ids] Windows LANGIDs; the primary language is the low 10 bits (0x09 English, 0x39 Hindi).
String focusFromLangIds(List<int> ids) {
  final primary = [for (final i in ids) i & 0x3FF];
  if (primary.contains(0x39)) return 'hindi';
  if (primary.any((p) => p != 0x09 && p != 0)) return 'multilingual';
  return 'english';
}
