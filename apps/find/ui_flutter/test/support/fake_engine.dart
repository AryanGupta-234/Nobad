import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/platform/window.dart';
import 'package:nobad_find/engine/fake_engine.dart';

export 'package:nobad_find/engine/fake_engine.dart';

class FakeWindow implements WindowControl {
  final calls = <String>[];
  final fits = <int>[];
  final looks = <(bool, bool)>[];
  @override
  void hide() => calls.add('hide');
  @override
  void showBar() => calls.add('showBar');
  @override
  void fitBar(int rows) => fits.add(rows);
  @override
  void front() => calls.add('front');
  @override
  bool look({required bool dark, required bool glass, required int canvasRgb}) {
    looks.add((dark, glass));
    return false;
  }

  @override
  void close() => calls.add('close');
  @override
  int get handle => 0;
}

/// The main window at 1080 x 720, connected to [engine].
Future<FakeWindow> pumpApp(
  WidgetTester tester,
  FakeEngine engine, {
  FakeWindow? window,
  Size size = const Size(1080, 720),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final w = window ?? FakeWindow();
  await tester.pumpWidget(NobadFindApp(engine: engine, window: w, splash: false));
  await tester.pump();
  await tester.pump();
  return w;
}

/// Type into the search box and let the debounce run.
Future<void> type(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField).first, text);
  await tester.pump(const Duration(milliseconds: 120));
  await tester.pump(const Duration(milliseconds: 300)); // Home fades out
}

var _fontsLoaded = false;

/// The real Windows fonts (Segoe UI Variable, Cascadia Mono, Arial Black) for goldens, so the pictures show real
/// text instead of the test font's boxes. Missing fonts fall back to the test font (other machines).
Future<void> loadWindowsFonts() async {
  if (_fontsLoaded) return;
  _fontsLoaded = true;
  final dir = '${Platform.environment['WINDIR'] ?? r'C:\Windows'}\\Fonts';
  Future<void> load(String family, List<String> files) async {
    final loader = FontLoader(family);
    var any = false;
    for (final f in files) {
      final file = File('$dir\\$f');
      if (file.existsSync()) {
        loader.addFont(Future.value(ByteData.sublistView(file.readAsBytesSync())));
        any = true;
      }
    }
    if (any) await loader.load();
  }

  await load('Segoe UI Variable Text', ['SegUIVar.ttf']);
  await load('Segoe UI', ['segoeui.ttf', 'seguisb.ttf', 'segoeuib.ttf']);
  await load('Segoe UI Symbol', ['seguisym.ttf']);
  await load('Cascadia Mono', ['CascadiaMono.ttf']);
  await load('Consolas', ['consola.ttf']);
  await load('NOBAD Display', ['ariblk.ttf']);
}
