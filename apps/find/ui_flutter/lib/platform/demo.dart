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
import '../engine/engine_api.dart';
import '../features/consent/download_consent_dialog.dart';
import '../state/search_controller.dart';
import 'timing.dart';

final shotBoundary = GlobalKey(debugLabel: 'demo shot');
final appNavigator = GlobalKey<NavigatorState>(debugLabel: 'app navigator');

class Demo {
  Demo._(this._queries, {this.isTour = false});
  final List<String> _queries;
  final bool isTour;

  /// Null unless NOBAD_FIND_UI_DEMO is set ("1" for the default searches, `a|b|c`, or "tour").
  static Demo? fromEnvironment() {
    final v = Platform.environment['NOBAD_FIND_UI_DEMO'];
    if (v == null || v.isEmpty) return null;
    if (v == 'tour') return Demo._(const [], isTour: true);
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

  /// The screenshot tour of the main window.
  Future<void> tour(AppScope s) async {
    if (!isTour) return;
    await _until(() => s.engine.link.value == Link.connected && s.settings.loaded);
    await _wait(1200);
    if (!s.settings.settings.flag('welcome_seen')) {
      await _shot('tour-welcome-dark.png');
      await s.settings.set('welcome_seen', true);
    }
    for (final theme in ['dark', 'light']) {
      if (s.settings.settings.text('theme') != theme) await s.settings.set('theme', theme);
      await _wait(700);
      s.nav.go(AppTab.search);
      await s.engine.toMain('');
      await _wait(1200);
      await _shot('tour-home-$theme.png');
      await s.engine.toMain('tax');
      await _wait(700);
      s.find.move(1);
      await _wait(500);
      await _shot('tour-results-$theme.png');
      await s.engine.toMain('');
      s.nav.go(AppTab.indexing);
      await _wait(1500);
      await _shot('tour-index-$theme.png');
      for (final p in [
        SettingsPage.general,
        SettingsPage.models,
        SettingsPage.performance,
        SettingsPage.privacy,
        SettingsPage.about,
      ]) {
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
      final image = await ro.toImage(pixelRatio: 1);
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      if (png != null) File('$dir${Platform.pathSeparator}$name').writeAsBytesSync(png.buffer.asUint8List());
    } catch (_) {
      // measurement only
    }
  }
}
