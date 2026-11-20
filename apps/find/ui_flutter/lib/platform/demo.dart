/// Measurement and screenshots only (docs/measurements.md). Off unless asked for:
/// - NOBAD_FIND_UI_DEMO=1 (or `a|b|c`): the window types a few fixed searches into its own box, one letter every
///   120 ms, writes how long each answer took (never the words) to NOBAD_FIND_UI_TIMING, and saves pictures of itself
///   to NOBAD_FIND_UI_SHOT_DIR. Used because the reference PC may be locked during a run (no keyboard or capture).
/// - NOBAD_FIND_UI_DEMO=tour: goes through every main screen in dark and then light (welcome, Home, results,
///   Index, Settings pages, the consent dialog) and saves a picture of each. Meant for NOBAD_FIND_FAKE_ENGINE=1.
library;

import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';

import '../app/scope.dart';
import '../app/theme/colors.dart';
import '../engine/engine_api.dart';
import '../features/consent/download_consent_dialog.dart';
import '../state/search_controller.dart';
import 'timing.dart';

final shotBoundary = GlobalKey(debugLabel: 'demo shot');
final appNavigator = GlobalKey<NavigatorState>(debugLabel: 'app navigator');

class Demo {
  Demo._(this._queries, {this.isTour = false, this.keepSettings = false});
  final List<String> _queries;
  final bool isTour;

  /// `tour-current`: only the theme already set, changing no setting (safe on someone else's engine).
  final bool keepSettings;

  /// Null unless NOBAD_FIND_UI_DEMO is set ("1" for the default searches, `a|b|c`, or "tour").
  static Demo? fromEnvironment() {
    final v = Platform.environment['NOBAD_FIND_UI_DEMO'];
    if (v == null || v.isEmpty) return null;
    if (v == 'tour') return Demo._(const [], isTour: true);
    if (v == 'tour-current') return Demo._(const [], isTour: true, keepSettings: true);
    return Demo._(v == '1' ? const ['tax', 'beach photo', 'invoice march', 'notes', 'budget'] : v.split('|'));
  }

  static Future<void> _until(bool Function() ok) async {
    while (!ok()) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
  }

  static Future<void> _wait([int ms = 900]) => Future<void>.delayed(Duration(milliseconds: ms));

  Future<void> run(
    EngineApi engine,
    TextEditingController box,
    FindController find,
    String mode, {
    void Function()? after,
  }) async {
    if (isTour) return;
    await _until(() => engine.link.value == Link.connected);
    await _wait(1000);
    var n = 0;
    for (final q in _queries) {
      box.clear();
      for (var i = 1; i <= q.length; i++) {
        box.text = q.substring(0, i);
        await _wait(120);
      }
      await _wait(900);
      recordTiming(
        'search $mode #$n chars=${q.length} results=${find.results.length} ui_ms=${find.lastMs} '
        'engine_ms=${find.answer.ms}',
      );
      find.move(1);
      await _wait(200);
      if (n < 2) await _shot('nobadfind-flutter-$mode-$n.png');
      n++;
    }
    recordTiming('demo-done $mode');
    after?.call();
  }

  /// The main window's search box, for the typing demo (set by the search screen).
  static TextEditingController? mainBox;

  /// Starts the demo for the main window: the screenshot tour, or the typing demo in the search box.
  Future<void> start(AppScope s) async {
    if (!isTour) {
      await _until(() => mainBox != null);
      return run(s.engine, mainBox!, s.find, 'main');
    }
    return tour(s);
  }

  /// Words into this window's box. `tour-current` (someone else's engine) keeps it inside this window: the engine's
  /// to_main would bring every connected window up with the words.
  Future<void> _type(AppScope s, String text) async {
    if (keepSettings) {
      s.find.handOver(text);
    } else {
      await s.engine.toMain(text);
    }
  }

  /// The screenshot tour of the main window.
  Future<void> tour(AppScope s) async {
    if (!isTour) return;
    await _until(() => s.engine.link.value == Link.connected && s.settings.loaded);
    await _wait(1200);
    if (!s.settings.settings.flag('welcome_seen')) {
      await _shot('tour-welcome-dark.png');
      if (!keepSettings) await s.settings.set('welcome_seen', true);
    }
    for (final theme in keepSettings ? [s.settings.settings.text('theme')] : ['dark', 'light']) {
      if (s.settings.settings.text('theme') != theme) await s.settings.set('theme', theme);
      await _wait(700);
      s.nav.go(AppTab.search);
      await _type(s, '');
      await _wait(1200);
      await _shot('tour-home-$theme.png');
      await _type(s, 'tax');
      await _wait(700);
      s.find.move(1);
      await _wait(500);
      await _shot('tour-results-$theme.png');
      await _type(s, '');
      s.nav.go(AppTab.indexing);
      await _wait(1500);
      await _shot('tour-index-$theme.png');
      for (final p in SettingsPage.values) {
        s.nav.openSettings(p);
        await _wait(800);
        await _shot('tour-settings-${p.name}-$theme.png');
      }
      final ctx = appNavigator.currentContext;
      if (ctx != null && ctx.mounted) {
        unawaited(askDownloadConsent(ctx, 'meaning'));
        await _wait(700);
        await _shot('tour-consent-$theme.png');
        appNavigator.currentState?.pop(false);
        await _wait(400);
      }
    }
    s.nav.go(AppTab.search);
    recordTiming('tour-done');
  }

  static Future<void> _shot(String name) async {
    final dir = Platform.environment['NOBAD_FIND_UI_SHOT_DIR'];
    final ro = shotBoundary.currentContext?.findRenderObject();
    if (dir == null || dir.isEmpty || ro is! RenderRepaintBoundary) return;
    try {
      final shot = await ro.toImage(pixelRatio: 1);
      // over glass the window is see-through (Mica behind it): put the picture on the theme's base colour
      final ctx = shotBoundary.currentContext;
      final base = ctx != null && ctx.mounted ? NbColors.of(ctx).bg : const Color(0xFF000000);
      final rec = ui.PictureRecorder();
      ui.Canvas(rec)
        ..drawColor(base, BlendMode.src)
        ..drawImage(shot, Offset.zero, ui.Paint());
      final image = await rec.endRecording().toImage(shot.width, shot.height);
      shot.dispose();
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      if (png != null) File('$dir${Platform.pathSeparator}$name').writeAsBytesSync(png.buffer.asUint8List());
    } catch (_) {
      // measurement only
    }
  }
}
