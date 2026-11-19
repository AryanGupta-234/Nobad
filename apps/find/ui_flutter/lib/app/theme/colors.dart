/// NOBAD colour tokens for frosted spatial glass: a deep (or pale) backdrop with two soft glows, the NOBAD orange
/// and a cool indigo, and translucent layers over it: panels, cards and popovers, each with a fine light rim.
///
/// Screens read them with `NbColors.of(context)`; nothing outside lib/app/theme hard-codes a colour.
library;

import 'package:flutter/widgets.dart';
import 'package:material_ui/material_ui.dart' show Theme, ThemeExtension;

@immutable
class NbColors extends ThemeExtension<NbColors> {
  const NbColors({
    required this.brightness,
    required this.orange,
    required this.onOrange,
    required this.bg,
    required this.surface,
    required this.raised,
    required this.text,
    required this.muted,
    required this.dim,
    required this.line,
    required this.line2,
    required this.warn,
    required this.danger,
    required this.shadow,
    this.glass = false,
  });

  final Brightness brightness;

  /// The one NOBAD orange. Light uses the darker step from app.css so orange text on white keeps its contrast.
  final Color orange;
  final Color onOrange;

  /// Window canvas, panels, and controls inside panels.
  final Color bg;
  final Color surface;
  final Color raised;
  final Color text;
  final Color muted;
  final Color dim;

  /// Hairlines (dividers, panel edges) and outlines (controls).
  final Color line;
  final Color line2;
  final Color warn;
  final Color danger;
  final Color shadow;

  /// Windows draws Mica/acrylic behind the window: the canvas is see-through and panels are tinted glass.
  final bool glass;

  bool get isDark => brightness == Brightness.dark;
  Color orangeA(double a) => orange.withValues(alpha: a);

  /// The window canvas under the backdrop: clear over Mica, solid otherwise.
  Color get canvas => glass ? bg.withValues(alpha: isDark ? .55 : .62) : bg;

  /// Floating panels (dock, palette, detail pane): frosted glass.
  /// Neutral dark at 76 % over Mica (no white haze), or white at 84 %.
  Color get panel => isDark ? const Color(0xC2141518) : const Color(0xD6FFFFFF);

  /// The dock, a little quieter than panels.
  Color get rail => isDark ? const Color(0xB8111214) : const Color(0xC7FFFFFF);

  /// Cards on the backdrop: fainter than panels, brighter when hovered.
  Color get card => isDark ? const Color(0xA6141518) : const Color(0xBFFFFFFF);
  Color get cardHover => isDark ? const Color(0x0FFFFFFF) : const Color(0x0A000000);

  /// A selected row: a quiet lift, the orange only in its small indicator.
  Color get selected => isDark ? const Color(0x17FFFFFF) : const Color(0x12000000);

  /// The 1 px light rim on the top edge of glass, fading down the sides.
  Color get rimLight => isDark ? const Color(0x1FFFFFFF) : const Color(0x1A000000);
  Color get rimShade => isDark ? const Color(0x14FFFFFF) : const Color(0x14000000);

  /// The backdrop's two glows.
  Color get glowWarm => orange.withValues(alpha: isDark ? .07 : .05);
  Color get glowCool => isDark ? const Color(0x124F5DFF) : const Color(0x0F4F5DFF);

  /// The soft shadow under floating things.
  Color get float => isDark ? const Color(0x73000000) : const Color(0x1A1B2440);

  static const dark = NbColors(
    brightness: Brightness.dark,
    orange: Color(0xFFFF4D00),
    onOrange: Color(0xFF000000),
    bg: Color(0xFF08090B), // near black (0.7.0)
    surface: Color(0xFF161922),
    raised: Color(0x14FFFFFF),
    text: Color(0xFFF4F5F8),
    muted: Color(0xA3FFFFFF), // white .64: secondary text
    dim: Color(0x85FFFFFF), // white .52: still over 4.5:1 on the canvas
    line: Color(0x14FFFFFF), // .08
    line2: Color(0x26FFFFFF), // .15
    warn: Color(0xFFFFB38A),
    danger: Color(0xFFFF8A8A),
    shadow: Color(0xFF000000),
  );

  static const light = NbColors(
    brightness: Brightness.light,
    orange: Color(0xFFE84400),
    onOrange: Color(0xFFFFFFFF),
    bg: Color(0xFFE7EAF1),
    surface: Color(0xFFFBFBFD),
    raised: Color(0x0F1B2440),
    text: Color(0xFF12141A),
    muted: Color(0xB816181C), // .72
    dim: Color(0x8516181C), // .52
    line: Color(0x17000000), // .09
    line2: Color(0x2E000000), // .18
    warn: Color(0xFFB33A00),
    danger: Color(0xFFB3261E),
    shadow: Color(0x33000000),
  );

  static NbColors of(BuildContext context) => Theme.of(context).extension<NbColors>() ?? dark;

  NbColors withGlass(bool on) => on == glass
      ? this
      : NbColors(
          brightness: brightness,
          orange: orange,
          onOrange: onOrange,
          bg: bg,
          surface: surface,
          raised: raised,
          text: text,
          muted: muted,
          dim: dim,
          line: line,
          line2: line2,
          warn: warn,
          danger: danger,
          shadow: shadow,
          glass: on,
        );

  @override
  NbColors copyWith() => this;

  @override
  NbColors lerp(NbColors? other, double t) {
    if (other == null) return this;
    Color l(Color a, Color b) => Color.lerp(a, b, t)!;
    return NbColors(
      brightness: t < .5 ? brightness : other.brightness,
      orange: l(orange, other.orange),
      onOrange: l(onOrange, other.onOrange),
      bg: l(bg, other.bg),
      surface: l(surface, other.surface),
      raised: l(raised, other.raised),
      text: l(text, other.text),
      muted: l(muted, other.muted),
      dim: l(dim, other.dim),
      line: l(line, other.line),
      line2: l(line2, other.line2),
      warn: l(warn, other.warn),
      danger: l(danger, other.danger),
      shadow: l(shadow, other.shadow),
      glass: t < .5 ? glass : other.glass,
    );
  }
}
