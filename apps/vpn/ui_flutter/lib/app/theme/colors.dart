/// NOBAD VPN colour tokens: frosted spatial glass over a deep (or pale) backdrop, the one NOBAD orange for every
/// action, and three state colours that are only ever used to say what the protection state is: sealed (green,
/// a verified tunnel), connecting (amber) and blocked (red, the kill switch holds traffic). Adapted from NOBAD Find.
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
    required this.sealed,
    required this.amber,
    required this.blocked,
    required this.shadow,
    this.glass = false,
  });

  final Brightness brightness;

  /// The one NOBAD orange: buttons, selection, focus, the mark. Light uses a darker step for contrast on white.
  final Color orange;
  final Color onOrange;
  final Color bg;
  final Color surface;
  final Color raised;
  final Color text;
  final Color muted;
  final Color dim;
  final Color line;
  final Color line2;

  /// Protected: the tunnel is up and verified.
  final Color sealed;

  /// Connecting, a warning, a check that needs attention.
  final Color amber;

  /// Blocked by the kill switch, an error.
  final Color blocked;
  final Color shadow;

  /// Windows draws Mica behind the window: the canvas is see-through and panels are tinted glass.
  final bool glass;

  bool get isDark => brightness == Brightness.dark;
  Color orangeA(double a) => orange.withValues(alpha: a);

  Color get canvas => glass ? bg.withValues(alpha: isDark ? .55 : .62) : bg;
  /// Panels: neutral glass over Mica, never grey mud: the surface at 76 % (dark) / 80 % (light).
  Color get panel => surface.withValues(alpha: isDark ? .76 : .80);

  /// The 1 px edge of every panel: white 8 % on dark, black 8 % on light.
  Color get edge => isDark ? const Color(0x14FFFFFF) : const Color(0x14000000);
  Color get rail => surface.withValues(alpha: isDark ? .84 : .9);
  Color get card => raised.withValues(alpha: isDark ? .70 : .85);
  Color get cardHover => Color.lerp(raised, text, isDark ? .05 : .03)!;
  Color get rimLight => isDark ? const Color(0x2EFFFFFF) : const Color(0xF2FFFFFF);
  Color get rimShade => isDark ? const Color(0x08FFFFFF) : const Color(0x14000000);
  /// The page's two glows (index.html g11): the NOBAD orange high on the left, a deeper orange low on the right.
  Color get glowWarm => orange.withValues(alpha: isDark ? .15 : .08);
  Color get glowCool => const Color(0xFFC43F00).withValues(alpha: isDark ? .10 : .05);

  /// design.css --hair: the gradient hairline round every card, warm at the top left, cool at the bottom right.
  List<Color> get hair => isDark
      ? const [Color(0x6BFF8A4C), Color(0x12FFFFFF), Color(0x0AFFFFFF), Color(0x3378A0FF)]
      : const [Color(0x42D6500A), Color(0x1A121A2C), Color(0x14121A2C), Color(0x2E466EDC)];
  Color get float => isDark ? const Color(0x73000000) : const Color(0x1A1B2440);

  /// A dialog's solid face when blur is off.
  Color get dialog => surface.withValues(alpha: isDark ? .94 : .97);

  /// The WebView UI's theme ("NOBAD g11", nobadvpn/ui/index.html and design.css), as the base under the glass.
  static const dark = NbColors(
    brightness: Brightness.dark,
    orange: Color(0xFFF65000),
    onOrange: Color(0xFFFFFFFF),
    bg: Color(0xFF08090D),
    surface: Color(0xFF111319),
    raised: Color(0xFF171A22),
    text: Color(0xFFF4F4F6),
    muted: Color(0xFFA0A1AA),
    dim: Color(0x99A0A1AA),
    line: Color(0x1BFFFFFF), // .105
    line2: Color(0x2BFFFFFF),
    sealed: Color(0xFF3BD69B),
    amber: Color(0xFFFF9A7C),
    blocked: Color(0xFFFF5268),
    shadow: Color(0xFF000000),
  );

  static const light = NbColors(
    brightness: Brightness.light,
    orange: Color(0xFFC94100),
    onOrange: Color(0xFFFFFFFF),
    bg: Color(0xFFE6E9EF),
    surface: Color(0xFFFFFFFF),
    raised: Color(0xFFF3F5F8),
    text: Color(0xFF121620),
    muted: Color(0xFF4E5665),
    dim: Color(0xB34E5665),
    line: Color(0x21121A2C), // .13
    line2: Color(0x33121A2C),
    sealed: Color(0xFF13865D),
    amber: Color(0xFFC4502F),
    blocked: Color(0xFFCC2942),
    shadow: Color(0x33000000),
  );

  static NbColors of(BuildContext context) => Theme.of(context).extension<NbColors>() ?? dark;

  NbColors withGlass(bool on) => on == glass ? this : _copy(glass: on);

  NbColors _copy({bool? glass}) => NbColors(
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
    sealed: sealed,
    amber: amber,
    blocked: blocked,
    shadow: shadow,
    glass: glass ?? this.glass,
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
      sealed: l(sealed, other.sealed),
      amber: l(amber, other.amber),
      blocked: l(blocked, other.blocked),
      shadow: l(shadow, other.shadow),
      glass: t < .5 ? glass : other.glass,
    );
  }
}
