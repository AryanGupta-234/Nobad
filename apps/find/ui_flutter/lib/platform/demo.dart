/// Measurement only (docs/measurements.md): with NOBAD_FIND_UI_DEMO set, the window types a few fixed searches into
/// its own box, one letter every 120 ms, writes how long each answer took (never the words) to the
/// NOBAD_FIND_UI_TIMING file, and saves a picture of itself to NOBAD_FIND_UI_SHOT_DIR. Used because the reference
/// PC may be locked during a measurement run (no keyboard input or screen capture then). Off unless asked for.
library;

import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';

import '../engine/rpc.dart';
import '../state/search_controller.dart';
import 'timing.dart';

final shotBoundary = GlobalKey(debugLabel: 'demo shot');

class Demo {
  Demo._(this._queries);
  final List<String> _queries;

  /// Null unless NOBAD_FIND_UI_DEMO is set ("1" for the default searches, or `a|b|c`).
  static Demo? fromEnvironment() {
    final v = Platform.environment['NOBAD_FIND_UI_DEMO'];
    if (v == null || v.isEmpty) return null;
    return Demo._(v == '1' ? const ['tax', 'beach photo', 'invoice march', 'notes', 'budget'] : v.split('|'));
  }

  Future<void> run(Engine engine, TextEditingController box, FindController find, String mode,
      {void Function()? after}) async {
    while (engine.link.value != Link.connected) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    await Future<void>.delayed(const Duration(seconds: 1));
    var n = 0;
    for (final q in _queries) {
      box.clear();
      for (var i = 1; i <= q.length; i++) {
        box.text = q.substring(0, i);
        await Future<void>.delayed(const Duration(milliseconds: 120));
      }
      await Future<void>.delayed(const Duration(milliseconds: 900));
      recordTiming('search $mode #$n chars=${q.length} results=${find.results.length} ui_ms=${find.lastMs} '
          'engine_ms=${find.answer.ms}');
      find.move(1);
      await Future<void>.delayed(const Duration(milliseconds: 200));
      if (n < 2) await _shot('nobadfind-flutter-$mode-$n.png');
      n++;
    }
    recordTiming('demo-done $mode');
    after?.call();
  }

  static Future<void> _shot(String name) async {
    final dir = Platform.environment['NOBAD_FIND_UI_SHOT_DIR'];
    final ro = shotBoundary.currentContext?.findRenderObject();
    if (dir == null || dir.isEmpty || ro is! RenderRepaintBoundary) return;
    try {
      final image = await ro.toImage(pixelRatio: 1);
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      if (png != null) File('$dir${Platform.pathSeparator}$name').writeAsBytesSync(png.buffer.asUint8List());
    } catch (_) {
      // measurement only
    }
  }
}
