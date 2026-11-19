/// One icon set: Windows 11's own Fluent icons (the Segoe Fluent Icons font that ships with Windows 11, the icons of
/// Windows Settings; Segoe MDL2 Assets on Windows 10), drawn at 16 px. Nothing bundled.
library;

import 'package:flutter/widgets.dart';

enum NbGlyph {
  search(0xE721),
  rings(0xE9D9), // Diagnostic
  settings(0xE713),
  close(0xE8BB),
  chevron(0xE70D),
  check(0xE73E),
  folder(0xE8B7),
  plus(0xE710),
  pause(0xE769),
  play(0xE768),
  copy(0xE8C8),
  external(0xE8A7),
  home(0xE80F),
  globe(0xE774),
  star(0xE734),
  starFilled(0xE735),
  bolt(0xE945),
  refresh(0xE72C),
  shield(0xEA18),
  link(0xE71B),
  lifebuoy(0xE90F), // Repair
  power(0xE7E8),
  gift(0xE710), // Add
  lock(0xE72E),
  help(0xE897),
  list(0xEA37),
  palette(0xE790),
  wifi(0xE701);

  const NbGlyph(this.code);
  final int code;
}

class NbIcon extends StatelessWidget {
  const NbIcon(this.glyph, {super.key, this.size = 16, required this.color, this.stroke = 1.6});
  final NbGlyph glyph;
  final double size;
  final Color color;

  /// Kept for the call sites that set it; the font's own stroke is used.
  final double stroke;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: SizedBox.square(
      dimension: size,
      child: Center(
        child: Text(
          String.fromCharCode(glyph.code),
          textScaler: TextScaler.noScaling,
          style: TextStyle(
            fontFamily: 'Segoe Fluent Icons',
            fontFamilyFallback: const ['Segoe MDL2 Assets'],
            fontSize: size,
            height: 1,
            color: color,
          ),
        ),
      ),
    ),
  );
}
