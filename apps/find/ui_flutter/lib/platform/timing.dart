/// Start-up timing for measurements: milliseconds from the process's creation (GetProcessTimes) to now.
/// Written only when NOBAD_FIND_UI_TIMING names a file (docs/measurements.md); nothing is ever sent anywhere.
library;

import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart';

final class _FILETIME extends Struct {
  @Uint32()
  external int low;
  @Uint32()
  external int high;
}

int? msSinceProcessStart() {
  if (!Platform.isWindows) return null;
  final k32 = DynamicLibrary.open('kernel32.dll');
  final current = k32.lookupFunction<IntPtr Function(), int Function()>('GetCurrentProcess');
  final times = k32.lookupFunction<
      Int32 Function(IntPtr, Pointer<_FILETIME>, Pointer<_FILETIME>, Pointer<_FILETIME>, Pointer<_FILETIME>),
      int Function(int, Pointer<_FILETIME>, Pointer<_FILETIME>, Pointer<_FILETIME>, Pointer<_FILETIME>)>(
      'GetProcessTimes');
  final now = k32.lookupFunction<Void Function(Pointer<_FILETIME>), void Function(Pointer<_FILETIME>)>(
      'GetSystemTimePreciseAsFileTime');
  return using((a) {
    final created = a<_FILETIME>(), x = a<_FILETIME>(), k = a<_FILETIME>(), u = a<_FILETIME>(), n = a<_FILETIME>();
    if (times(current(), created, x, k, u) == 0) return null;
    now(n);
    int v(Pointer<_FILETIME> f) => (f.ref.high << 32) | f.ref.low;
    return (v(n) - v(created)) ~/ 10000; // 100 ns units
  });
}

void recordTiming(String what) {
  final path = Platform.environment['NOBAD_FIND_UI_TIMING'];
  if (path == null || path.isEmpty) return;
  final ms = msSinceProcessStart();
  try {
    File(path).writeAsStringSync('$what pid=$pid ms=$ms\n', mode: FileMode.append, flush: true);
  } on FileSystemException {
    // measurement only
  }
}
