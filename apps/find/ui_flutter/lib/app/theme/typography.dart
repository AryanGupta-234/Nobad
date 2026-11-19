/// Type, led by one face: Segoe UI Variable. Big display lines are set thin (weight 300) with tight tracking, the
/// confident, quiet voice of the frosted design; body text is Segoe UI Variable Text; Cascadia Mono only for
/// numbers and paths. System fonts only: nothing bundled, nothing downloaded.
///
/// The scale: 11 / 12 / 13 / 14 / 16 / 18 / 21 / 28 / 40 / 60.
library;

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

abstract final class NbFont {
  static const body = 'Segoe UI Variable Text';
  static const bodyFallback = ['Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol'];
  static const mono = 'Cascadia Mono';
  static const monoFallback = ['Consolas', 'Segoe UI', 'Segoe UI Symbol'];

  /// Segoe UI Variable (the variable font file), registered at start ([loadDisplayFont]) so its weight axis can be
  /// set exactly: asked for by name, Windows' font matching doesn't give the thin weights reliably.
  static const display = 'NOBAD Display';
  static const displayFallback = ['Segoe UI Variable Display', 'Segoe UI Light', 'Segoe UI'];
}

/// Registers Windows' own Segoe UI Variable (Fonts\SegUIVar.ttf in the Windows folder) as [NbFont.display].
/// Nothing is bundled or downloaded; without the file the fallbacks are used.
Future<void> loadDisplayFont() async {
  try {
    final dir = Platform.environment['WINDIR'] ?? r'C:\Windows';
    final f = File('$dir${Platform.pathSeparator}Fonts${Platform.pathSeparator}SegUIVar.ttf');
    if (!f.existsSync()) return;
    final bytes = await f.readAsBytes();
    await (FontLoader(NbFont.display)..addFont(Future.value(ByteData.sublistView(bytes)))).load();
  } on Object {
    // the fallbacks draw it
  }
}

abstract final class NbSize {
  static const micro = 10.5;
  static const caption = 11.5;
  static const small = 12.5;
  static const body = 14.0;
  static const title = 16.0;
  static const lead = 18.0;
  static const field = 21.0;
  static const page = 40.0;
  static const hero = 60.0;
}

abstract final class NbType {
  /// Reading text. Line height 1.5 for paragraphs; single lines pass [height] 1.3.
  static TextStyle text(double size, Color color, {FontWeight weight = FontWeight.w400, double? height}) => TextStyle(
    fontFamily: NbFont.body,
    fontFamilyFallback: NbFont.bodyFallback,
    fontSize: size,
    fontWeight: weight,
    color: color,
    height: height,
    letterSpacing: size >= NbSize.lead ? -0.01 * size : 0,
  );

  /// Data: paths, numbers, times. Tabular figures so columns of numbers line up.
  static TextStyle data(double size, Color color, {FontWeight weight = FontWeight.w400, double? height}) => TextStyle(
    fontFamily: NbFont.mono,
    fontFamilyFallback: NbFont.monoFallback,
    fontSize: size,
    fontWeight: weight,
    color: color,
    height: height,
    fontFeatures: const [FontFeature.tabularFigures()],
  );

  /// Display lines: thin, tight, sentence case. [weight] on the variable font's axis (300 = light).
  static TextStyle display(double size, Color color, {double weight = 300}) => TextStyle(
    fontFamily: NbFont.display,
    fontFamilyFallback: NbFont.displayFallback,
    fontSize: size,
    fontWeight: weight <= 350 ? FontWeight.w300 : FontWeight.w500,
    fontVariations: [FontVariation('wght', weight), FontVariation('opsz', size.clamp(8, 36).toDouble())],
    color: color,
    height: 1.06,
    letterSpacing: -0.028 * size,
  );
}
