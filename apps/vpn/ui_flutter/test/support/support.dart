/// Test helpers: the real Windows fonts for goldens, a recording window, pumping the app.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_vpn_ui/app/app.dart';
import 'package:nobad_vpn_ui/app/scope.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/engine/rpc.dart';
import 'package:nobad_vpn_ui/platform/files.dart';
import 'package:nobad_vpn_ui/platform/window.dart';

class FakeWindow implements WindowControl {
  final calls = <String>[];
  @override
  void hide() => calls.add('hide');
  @override
  void showMini() => calls.add('showMini');
  @override
  void front() => calls.add('front');
  @override
  bool look({required bool dark, required bool glass, required int canvasRgb}) {
    calls.add('look ${dark ? 'dark' : 'light'}');
    return false;
  }

  @override
  void close() => calls.add('close');
  @override
  bool spawn(String window) {
    calls.add('spawn $window');
    return true;
  }

  @override
  int get handle => 0;
}

/// The map's clock in tests: the daylight in the goldens never changes.
final fixedNow = DateTime.utc(2026, 11, 19, 9, 30);

var _fontsLoaded = false;

/// Arial Black, Segoe UI Variable, Cascadia Mono from C:\Windows\Fonts (read synchronously: real IO futures don't
/// complete inside a widget test's fake clock).
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

  await load('NOBAD Display', ['ariblk.ttf']);
  await load('Segoe UI Variable Text', ['SegUIVar.ttf']);
  await load('Segoe UI', ['segoeui.ttf', 'seguisb.ttf', 'segoeuib.ttf']);
  await load('Segoe UI Symbol', ['seguisym.ttf']);
  await load('Cascadia Mono', ['CascadiaMono.ttf']);
  await load('Consolas', ['consola.ttf']);
  await load('Segoe Fluent Icons', ['SegoeIcons.ttf']);
  await load('Segoe MDL2 Assets', ['segmdl2.ttf']);
}

Future<FakeWindow> pumpApp(
  WidgetTester tester,
  FakeEngine engine, {
  Size size = const Size(1280, 820),
  AppMode mode = AppMode.main,
  AppTab tab = AppTab.home,
  FilePicker files = const NoFilePicker(),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final w = FakeWindow();
  await tester.pumpWidget(NobadVpnApp(
    engine: engine,
    window: w,
    mode: mode,
    tab: tab,
    files: files,
    reduceMotion: true,
    splash: false,
    now: () => fixedNow,
  ));
  await tester.pump();
  await tester.pump();
  return w;
}

/// Lines in, lines out, for RpcSession / EngineClient tests.
class FakeTransport implements Transport {
  final _in = StreamController<String>();
  final sent = <String>[];
  void Function(String line)? onSend;
  bool closed = false;

  void reply(String line) => _in.add(line);

  @override
  Stream<String> get lines => _in.stream;
  @override
  void send(String line) {
    if (closed) throw const EngineOffline();
    sent.add(line);
    onSend?.call(line);
  }

  @override
  Future<void> close() async {
    if (closed) return;
    closed = true;
    await _in.close();
  }
}

/// Lets a widget test's pending engine futures and timers run out.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}
