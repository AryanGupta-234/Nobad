/// NOBAD Find UI (prototype). No arguments: the main search window. `--bar`: the quick find bar.
/// Talks only to the NOBAD Find engine (`python -m nobadfind --engine`) over the user's private named pipe.
library;

import 'package:material_ui/material_ui.dart';

import 'app/app.dart';
import 'engine/pipe_client.dart';
import 'engine/rpc.dart';
import 'platform/demo.dart';
import 'platform/timing.dart';
import 'platform/window.dart';

void main(List<String> args) {
  WidgetsFlutterBinding.ensureInitialized();
  final mode = args.contains('--bar') ? AppMode.bar : AppMode.main;
  final engine = EngineClient(PipeTransport.connect)..start();
  runApp(NobadFindApp(engine: engine, mode: mode, window: Win32Window.create(), demo: Demo.fromEnvironment()));
  WidgetsBinding.instance.waitUntilFirstFrameRasterized.then((_) => recordTiming('first-frame ${mode.name}'));
}
