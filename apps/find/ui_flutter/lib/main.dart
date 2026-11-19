/// NOBAD Find UI. No arguments: the main window. `--bar`: the quick find bar.
/// Talks only to the NOBAD Find engine (`python -m nobadfind --engine`) over the user's private named pipe.
/// NOBAD_FIND_FAKE_ENGINE=1 runs against the in-memory FakeEngine instead (screenshots, design work).
library;

import 'dart:io' show Platform;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import 'app/app.dart';
import 'app/theme/typography.dart';
import 'engine/engine_api.dart';
import 'engine/events.dart';
import 'engine/fake_engine.dart';
import 'engine/pipe_client.dart';
import 'engine/rpc.dart';
import 'engine/wiring.dart';
import 'platform/demo.dart';
import 'platform/timing.dart';
import 'platform/window.dart';

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  await loadDisplayFont(); // one 170 KB file from C:\Windows\Fonts, a millisecond
  // Skia keeps up to 256 MB of GPU resources by default; this UI redraws text and a few paths, so a small cache is
  // plenty and keeps the window's memory down (docs/measurements.md).
  final cacheMb = int.tryParse(Platform.environment['NOBAD_FIND_SKIA_CACHE_MB'] ?? '') ?? 12;
  Win32Window.shownCacheBytes = cacheMb << 20;
  SystemChannels.skia.invokeMethod<void>('Skia.setResourceCacheMaxBytes', cacheMb << 20);
  final mode = args.contains('--bar') ? AppMode.bar : AppMode.main;
  final EngineApi engine;
  if (Platform.environment['NOBAD_FIND_FAKE_ENGINE'] == '1') {
    engine = FakeEngine(
      files: demoFiles(),
      live: true,
      settings: {
        'welcome_seen': Platform.environment['NOBAD_FIND_FAKE_WELCOME'] == '0',
        if (Platform.environment['NOBAD_FIND_FAKE_GLASS'] == '0') 'glass': false,
      },
    );
  } else {
    final pipe = EngineClient(
      PipeTransport.connect,
      subscribeTo: mode == AppMode.bar ? EngineEvent.bar : EngineEvent.mainWindow,
      window: mode == AppMode.bar ? 'bar' : 'main',
    )..start();
    engine = PipeEngine(pipe, beforeDialog: allowSetForeground); // never the fake: offline is shown as offline
  }
  runApp(NobadFindApp(engine: engine, mode: mode, window: Win32Window.create(), demo: Demo.fromEnvironment()));
  WidgetsBinding.instance.waitUntilFirstFrameRasterized.then((_) => recordTiming('first-frame ${mode.name}'));
}
