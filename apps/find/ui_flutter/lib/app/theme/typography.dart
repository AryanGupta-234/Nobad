/// Type: system fonts only (nothing bundled, works offline, no extra RAM), the same three families as app.css.
///
/// - Arial Black, upper case: one display line per screen ("Find anything on this PC.", the level on Indexing).
/// - Segoe UI Variable: everything people read.
/// - Cascadia Mono: data only (paths, sizes, counts, times, key caps), never decoration.
///
/// The scale is the classic 11 / 12 / 13 / 14 / 16 / 18 / 21 / 28 / 44 ladder (The Elements of Typographic Style).
library;

import 'package:flutter/widgets.dart';

abstract final class NbFont {
  static const body = 'Segoe UI Variable Text';
  static const bodyFallback = ['Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol'];
  static const mono = 'Cascadia Mono';
  static const monoFallback = ['Consolas', 'Segoe UI', 'Segoe UI Symbol'];
  static const display = 'Arial Black';
  static const displayFallback = ['Segoe UI Black', 'Segoe UI'];
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
  static TextStyle text(double size, Color color, {FontWeight weight = FontWeight.w400, double? height}) =>
      TextStyle(fontFamily: NbFont.body, fontFamilyFallback: NbFont.bodyFallback, fontSize: size, fontWeight: weight,
          color: color, height: height, letterSpacing: size >= NbSize.lead ? -0.01 * size : 0);

  /// Data: paths, numbers, times. Tabular figures so columns of numbers line up.
  static TextStyle data(double size, Color color, {FontWeight weight = FontWeight.w400, double? height}) =>
      TextStyle(fontFamily: NbFont.mono, fontFamilyFallback: NbFont.monoFallback, fontSize: size, fontWeight: weight,
          color: color, height: height, fontFeatures: const [FontFeature.tabularFigures()]);

  /// The one display line per screen. Callers upper-case the words (the 0.7.0 look).
  static TextStyle display(double size, Color color) => TextStyle(fontFamily: NbFont.display,
      fontFamilyFallback: NbFont.displayFallback, fontSize: size, color: color, height: 1.02,
      letterSpacing: -0.03 * size);
}
