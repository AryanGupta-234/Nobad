/// Picking WireGuard files to import: Windows' own Open dialog (comdlg32 through dart:ffi), in this window's
/// process, as the signed-in user. The files are read here and only their TEXT goes to the engine (`import`), so
/// the elevated engine never opens a path the user (or anyone) chose. That's stricter than the WebView, which also
/// sent text, and the same idea.
library;

import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';

import 'package:ffi/ffi.dart';

import 'qr.dart' show imageExtensions;

class PickedFile {
  const PickedFile(this.name, this.text, {this.bytes});
  final String name;

  /// The file as text (configs), and as bytes for a picture (a QR code).
  final String text;
  final Uint8List? bytes;
}

/// Reads files the user picked or dropped, as the user: configs up to [maxBytes] as text, pictures up to
/// [maxImageBytes] as bytes. Anything else, too big or unreadable is skipped.
Future<List<PickedFile>> readPicked(List<String> paths) async {
  final out = <PickedFile>[];
  for (final p in paths) {
    try {
      final f = File(p);
      final name = p.split(Platform.pathSeparator).last;
      final image = imageExtensions.contains(name.split('.').last.toLowerCase());
      if (!f.existsSync() || f.lengthSync() > (image ? maxImageBytes : maxBytes)) continue;
      final bytes = await f.readAsBytes();
      out.add(PickedFile(name, image ? '' : utf8.decode(bytes, allowMalformed: true), bytes: image ? bytes : null));
    } on Object {
      // unreadable: skipped
    }
  }
  return out;
}

abstract class FilePicker {
  /// The files the user chose (name and text), or an empty list. Files over [maxBytes] are skipped.
  Future<List<PickedFile>> pickConfigs(int owner);
}

class NoFilePicker implements FilePicker {
  const NoFilePicker([this.files = const []]);
  final List<PickedFile> files;
  @override
  Future<List<PickedFile>> pickConfigs(int owner) async => files;
}

const maxBytes = 400000;
const maxImageBytes = 12 * 1024 * 1024;

final class _OPENFILENAMEW extends Struct {
  @Uint32()
  external int lStructSize;
  @IntPtr()
  external int hwndOwner;
  @IntPtr()
  external int hInstance;
  external Pointer<Utf16> lpstrFilter;
  external Pointer<Utf16> lpstrCustomFilter;
  @Uint32()
  external int nMaxCustFilter;
  @Uint32()
  external int nFilterIndex;
  external Pointer<Utf16> lpstrFile;
  @Uint32()
  external int nMaxFile;
  external Pointer<Utf16> lpstrFileTitle;
  @Uint32()
  external int nMaxFileTitle;
  external Pointer<Utf16> lpstrInitialDir;
  external Pointer<Utf16> lpstrTitle;
  @Uint32()
  external int flags;
  @Uint16()
  external int nFileOffset;
  @Uint16()
  external int nFileExtension;
  external Pointer<Utf16> lpstrDefExt;
  @IntPtr()
  external int lCustData;
  @IntPtr()
  external int lpfnHook;
  external Pointer<Utf16> lpTemplateName;
  external Pointer<Void> pvReserved;
  @Uint32()
  external int dwReserved;
  @Uint32()
  external int flagsEx;
}

class WindowsFilePicker implements FilePicker {
  const WindowsFilePicker();

  @override
  Future<List<PickedFile>> pickConfigs(int owner) async {
    return readPicked(_dialog(owner));
  }

  List<String> _dialog(int owner) {
    final dll = DynamicLibrary.open('comdlg32.dll');
    final open = dll.lookupFunction<Int32 Function(Pointer<_OPENFILENAMEW>), int Function(Pointer<_OPENFILENAMEW>)>(
        'GetOpenFileNameW');
    const size = 32768;
    return using((a) {
      final buf = a<Uint16>(size);
      // "label\0pattern\0...\0\0"
      final filterText = 'WireGuard configs and QR pictures\u0000*.conf;*.txt;*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp\u0000'
          'WireGuard configs (*.conf)\u0000*.conf;*.txt\u0000QR pictures\u0000*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp\u0000'
          'All files\u0000*.*\u0000\u0000';
      final filter = a<Uint16>(filterText.length);
      for (var i = 0; i < filterText.length; i++) {
        filter[i] = filterText.codeUnitAt(i);
      }
      final title = 'Import WireGuard configs'.toNativeUtf16(allocator: a);
      final ofn = a<_OPENFILENAMEW>();
      ofn.ref
        ..lStructSize = sizeOf<_OPENFILENAMEW>()
        ..hwndOwner = owner
        ..lpstrFilter = filter.cast()
        ..nFilterIndex = 1
        ..lpstrFile = buf.cast()
        ..nMaxFile = size
        ..lpstrTitle = title
        // OFN_EXPLORER | OFN_ALLOWMULTISELECT | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR
        ..flags = 0x80000 | 0x200 | 0x1000 | 0x800 | 0x8;
      if (open(ofn) == 0) return const <String>[];
      final parts = <String>[];
      var start = 0;
      for (var i = 0; i < size; i++) {
        if (buf[i] == 0) {
          if (i == start) break;
          parts.add(String.fromCharCodes(buf.asTypedList(size).sublist(start, i)));
          start = i + 1;
        }
      }
      if (parts.length <= 1) return parts;
      final dir = parts.first;
      return [for (final f in parts.skip(1)) '$dir${Platform.pathSeparator}$f'];
    });
  }
}
