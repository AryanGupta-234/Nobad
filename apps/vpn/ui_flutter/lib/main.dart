/// NOBAD VPN's window. No arguments: the main window. `--mini`: the tray pop-up.
///
/// It runs as the signed-in user, never elevated, and talks only to the NOBAD VPN engine (NobadVPN.exe, elevated)
/// over its private pipe `\\.\pipe\NOBADVPN-<user SID>` (contract: apps/vpn/contract). With no engine it says so;
/// it never makes up a state. Development switches (never set in an installed build):
/// - NOBAD_VPN_DEV_ENGINE=1: the unelevated demo engine's pipe (ui_flutter/tool/demo_engine.py), for screenshots;
/// - NOBAD_VPN_FAKE_ENGINE=1: the in-memory FakeEngine, no pipe at all (NOBAD_VPN_FAKE_CONNECTED=1 starts connected);
/// - NOBAD_VPN_UI_TAB=home|servers|settings: the screen the main window opens on.
library;

import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import 'app/app.dart';
import 'app/scope.dart';
import 'app/theme/typography.dart';
import 'engine/engine.dart';
import 'engine/fake_engine.dart';
import 'engine/pipe_client.dart';
import 'engine/rpc.dart';
import 'platform/files.dart';
import 'platform/window.dart';
import 'widgets/glass.dart';

/// True only in debug builds or with --dart-define=NOBAD_VPN_DEV=true (screenshots, the demo engine).
const devSwitches = kDebugMode || bool.fromEnvironment('NOBAD_VPN_DEV');

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  await loadDisplayFont(); // ariblk.ttf from the Windows fonts folder, a millisecond
  // Skia keeps up to 256 MB of GPU resources by default; this UI draws text and a few paths, so a small cache is
  // plenty and keeps the window's memory down (NOBAD Find measured the same, apps/find/docs/measurements.md).
  final cacheMb = (devSwitches ? int.tryParse(Platform.environment['NOBAD_VPN_SKIA_CACHE_MB'] ?? '') : null) ?? 12;
  Win32Window.shownCacheBytes = cacheMb << 20;
  SystemChannels.skia.invokeMethod<void>('Skia.setResourceCacheMaxBytes', cacheMb << 20);
  final mode = args.contains('--mini') ? AppMode.mini : AppMode.main;
  Win32Window.acrylic = mode == AppMode.mini;
  Glass.noBlur = devSwitches && Platform.environment['NOBAD_VPN_NO_BLUR'] == '1';
  // Development switches (a fake engine, the unelevated demo engine, a start tab) exist only in debug builds and in
  // builds made with --dart-define=NOBAD_VPN_DEV=true. A release build ignores them: anything running as the user can
  // set environment variables (HKCU\Environment), and must not be able to make the real window show a fake state.
  final env = devSwitches ? Platform.environment : const <String, String>{};
  final EngineApi engine;
  if (env['NOBAD_VPN_FAKE_ENGINE'] == '1') {
    engine = FakeEngine(state: demoState(connected: env['NOBAD_VPN_FAKE_CONNECTED'] == '1'), live: true);
  } else {
    final dev = env['NOBAD_VPN_DEV_ENGINE'] == '1';
    final pipe = EngineClient(
      () => PipeTransport.connect(dev: dev),
      subscribeTo: mode == AppMode.mini ? miniEvents : mainEvents,
      window: mode == AppMode.mini ? 'mini' : 'main',
    )..start();
    engine = PipeEngine(pipe); // never the fake: offline is shown as offline
  }
  final tab = AppTab.values.where((t) => t.name == env['NOBAD_VPN_UI_TAB']).firstOrNull ?? AppTab.home;
  runApp(NobadVpnApp(
    engine: engine,
    mode: mode,
    window: Win32Window.create(),
    files: const WindowsFilePicker(),
    tab: tab,
  ));
}
