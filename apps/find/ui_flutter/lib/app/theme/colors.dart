/// NOBAD colour tokens: one NOBAD orange, black or soft white, the same values as nobadfind/ui/app.css (0.7.0).
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

  /// The window canvas: clear over glass, solid otherwise.
  Color get canvas => glass ? bg.withValues(alpha: isDark ? .36 : .5) : bg;

  /// Panels: tinted glass over Mica, solid otherwise.
  Color get panel => glass ? surface.withValues(alpha: isDark ? .55 : .72) : surface;

  /// The left rail, a step apart from the canvas.
  Color get rail => glass ? surface.withValues(alpha: isDark ? .32 : .45) : surface;

  static const dark = NbColors(
    brightness: Brightness.dark,
    orange: Color(0xFFFF4D00),
    onOrange: Color(0xFF000000),
    bg: Color(0xFF07080A),
    surface: Color(0xFF0C0E11),
    raised: Color(0xFF12151A),
    text: Color(0xFFF3F4F6),
    muted: Color(0xADE8ECF1), // rgba(232, 236, 241, .68)
    dim: Color(0x73E8ECF1), // .45
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
    bg: Color(0xFFF6F5F3),
    surface: Color(0xFFFFFFFF),
    raised: Color(0xFFEFEDEA),
    text: Color(0xFF16181C),
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
