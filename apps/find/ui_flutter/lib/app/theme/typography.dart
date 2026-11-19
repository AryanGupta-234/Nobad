/// Type (the 0.7.0 look, kept by the maintainer): system fonts only, nothing bundled, nothing downloaded.
///
/// - Arial Black, upper case: one display line per screen ("Find anything on this PC.", the level on Index).
/// - Segoe UI Variable Text: everything people read.
/// - Cascadia Mono: data only (paths, sizes, counts, times, key caps).
///
/// The scale is the classic 11 / 12 / 13 / 14 / 16 / 18 / 21 / 28 / 44 ladder.
library;

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

abstract final class NbFont {
  static const body = 'Segoe UI Variable Text';

  /// Nirmala UI: Devanagari and the other Indic scripts (Hindi file names and snippets).
  static const bodyFallback = ['Segoe UI', 'Nirmala UI', 'Segoe UI Emoji', 'Segoe UI Symbol'];
  static const mono = 'Cascadia Mono';
  static const monoFallback = ['Consolas', 'Segoe UI', 'Nirmala UI', 'Segoe UI Symbol'];

  /// Arial Black, registered from the Windows fonts folder at start ([loadDisplayFont]): asked for by name,
  /// Windows' font matching gives plain Arial (Arial Black is a weight of the Arial family there).
  static const display = 'NOBAD Display';
  static const displayFallback = ['Arial Black', 'Segoe UI Black', 'Segoe UI'];
}

/// Registers Windows' own Arial Black (Fonts\ariblk.ttf in the Windows folder, 170 KB) as [NbFont.display].
/// Nothing is bundled or downloaded; without the file the fallbacks are used.
Future<void> loadDisplayFont() async {
  try {
    final dir = Platform.environment['WINDIR'] ?? r'C:\Windows';
    final f = File('$dir${Platform.pathSeparator}Fonts${Platform.pathSeparator}ariblk.ttf');
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
  static const page = 28.0;
  static const hero = 44.0;
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

  /// The one display line per screen. Callers upper-case the words (the 0.7.0 look).
  static TextStyle display(double size, Color color) => TextStyle(
    fontFamily: NbFont.display,
    fontFamilyFallback: NbFont.displayFallback,
    fontSize: size,
    color: color,
    height: 1.02,
    letterSpacing: -0.03 * size,
  );
}
