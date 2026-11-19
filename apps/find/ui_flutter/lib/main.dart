/// NOBAD Find UI. No arguments: the main window. `--bar`: the quick find bar.
/// Talks only to the NOBAD Find engine (`python -m nobadfind --engine`) over the user's private named pipe.
/// NOBAD_FIND_FAKE_ENGINE=1 runs against the in-memory FakeEngine instead (screenshots, design work).
library;

import 'dart:io' show Platform;

import 'package:material_ui/material_ui.dart';

import 'app/app.dart';
import 'engine/engine_api.dart';
import 'engine/events.dart';
import 'engine/fake_engine.dart';
import 'engine/pipe_client.dart';
import 'engine/rpc.dart';
import 'engine/wiring.dart';
import 'platform/demo.dart';
import 'platform/timing.dart';
import 'platform/window.dart';

void main(List<String> args) {
  WidgetsFlutterBinding.ensureInitialized();
  final mode = args.contains('--bar') ? AppMode.bar : AppMode.main;
  final EngineApi engine;
  if (Platform.environment['NOBAD_FIND_FAKE_ENGINE'] == '1') {
    engine = FakeEngine(files: demoFiles(), live: true, settings: const {'welcome_seen': false});
  } else {
    final pipe = EngineClient(PipeTransport.connect,
        subscribeTo: mode == AppMode.bar ? EngineEvent.bar : EngineEvent.mainWindow,
        window: mode == AppMode.bar ? 'bar' : 'main')
      ..start();
    engine = WiredEngine(pipe, beforeDialog: allowSetForeground);
  }
  runApp(NobadFindApp(engine: engine, mode: mode, window: Win32Window.create(), demo: Demo.fromEnvironment()));
  WidgetsBinding.instance.waitUntilFirstFrameRasterized.then((_) => recordTiming('first-frame ${mode.name}'));
}
