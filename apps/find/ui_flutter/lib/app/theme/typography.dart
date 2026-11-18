/// System fonts only (nothing bundled, works offline): Segoe UI Variable for text, Cascadia Mono for labels,
/// Arial Black for display headings, the same stacks as app.css.
library;

import 'package:flutter/widgets.dart';

import 'colors.dart';

abstract final class NbType {
  static const body = 'Segoe UI Variable Text';
  static const bodyFallback = ['Segoe UI', 'Segoe UI Emoji'];
  static const mono = 'Cascadia Mono';
  static const monoFallback = ['Consolas', 'Segoe UI'];
  static const display = 'Arial Black';
  static const displayFallback = ['Segoe UI Black', 'Segoe UI'];

  static TextStyle text(double size, {FontWeight weight = FontWeight.w400, Color color = Nb.text, double? height}) =>
      TextStyle(fontFamily: body, fontFamilyFallback: bodyFallback, fontSize: size, fontWeight: weight,
          color: color, height: height);

  static TextStyle label(double size,
          {FontWeight weight = FontWeight.w400, Color color = Nb.dim, double spacing = 0, double? height}) =>
      TextStyle(fontFamily: mono, fontFamilyFallback: monoFallback, fontSize: size, fontWeight: weight,
          color: color, letterSpacing: spacing, height: height);

  static TextStyle heading(double size, {Color color = Nb.text}) => TextStyle(fontFamily: display,
      fontFamilyFallback: displayFallback, fontSize: size, color: color, height: 1, letterSpacing: -0.03 * size);
}
