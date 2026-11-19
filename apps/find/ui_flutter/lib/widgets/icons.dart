/// The icons: Windows' Segoe Fluent Icons (system font), and the level glyph (the same four shapes everywhere a
/// work level is shown).
library;

import 'dart:math' as math;

import 'package:flutter/widgets.dart';

enum NbGlyph {
  search,
  rings,
  settings,
  close,
  chevron,
  check,
  folder,
  plus,
  pause,
  play,
  copy,
  external,
  // the sidebar's categories and Settings pages
  grid,
  doc,
  image,
  media,
  code,
  download,
  clock,
  sliders,
  drive,
  chip,
  gauge,
  shield,
  keyboard,
  info,
  more,
}

/// Windows 11's own outline icons (the Segoe Fluent Icons font that ships with Windows; nothing bundled), one set
/// at 16 px everywhere. On Windows 10 the older Segoe MDL2 Assets font has the same code points.
class NbIcon extends StatelessWidget {
  const NbIcon(this.glyph, {super.key, this.size = 16, required this.color, this.stroke = 1.6});
  final NbGlyph glyph;
  final double size;
  final Color color;

  /// Kept for callers; the font's strokes are Windows' own.
  final double stroke;

  static const family = 'Segoe Fluent Icons';
  static const fallback = ['Segoe MDL2 Assets'];

  static const codes = {
    NbGlyph.search: 0xE721,
    NbGlyph.rings: 0xE8F1, // Library: the index
    NbGlyph.settings: 0xE713,
    NbGlyph.close: 0xE711,
    NbGlyph.chevron: 0xE70D,
    NbGlyph.check: 0xE73E,
    NbGlyph.folder: 0xED25, // open folder: show in folder
    NbGlyph.plus: 0xE710,
    NbGlyph.pause: 0xE769,
    NbGlyph.play: 0xE768,
    NbGlyph.copy: 0xE8C8,
    NbGlyph.external: 0xE8A7, // open
    NbGlyph.grid: 0xE71D,
    NbGlyph.doc: 0xE8A5,
    NbGlyph.image: 0xE91B,
    NbGlyph.media: 0xE714,
    NbGlyph.code: 0xE943,
    NbGlyph.download: 0xE896,
    NbGlyph.clock: 0xE81C,
    NbGlyph.sliders: 0xE9E9,
    NbGlyph.drive: 0xEDA2,
    NbGlyph.chip: 0xEEA1,
    NbGlyph.gauge: 0xEC4A,
    NbGlyph.shield: 0xEA18,
    NbGlyph.keyboard: 0xE765,
    NbGlyph.info: 0xE946,
    NbGlyph.more: 0xE712,
  };

  @override
  Widget build(BuildContext context) => SizedBox.square(
    dimension: size,
    // the glyph is a private-use character: never read out (the control it is on has the words)
    child: ExcludeSemantics(
      child: Center(
        child: Text(
          String.fromCharCode(codes[glyph]!),
          textScaler: TextScaler.noScaling,
          style: TextStyle(fontFamily: family, fontFamilyFallback: fallback, fontSize: size, height: 1, color: color),
        ),
      ),
    ),
  );
}

class LevelGlyph extends StatelessWidget {
  const LevelGlyph({
    super.key,
    required this.level,
    required this.color,
    required this.dim,
    this.size = 12,
    this.glow = true,
  });
  final String level;
  final Color color;
  final Color dim;
  final double size;
  final bool glow;

  static _Shape _shapeOf(String level) => switch (level) {
    'full' => const _Shape(1, 0, 1),
    'gentle' => const _Shape(.5, 0, 0),
    'paused' => const _Shape(0, 1, 0),
    _ => const _Shape(0, 0, 0),
  };

  @override
  Widget build(BuildContext context) {
    final off = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    return Semantics(
      label: const {'full': 'Full speed', 'gentle': 'Gentle', 'light': 'Very light', 'paused': 'Paused'}[level],
      child: SizedBox.square(
        dimension: size,
        child: TweenAnimationBuilder<_Shape>(
          tween: _ShapeTween(end: _shapeOf(level)),
          duration: off ? Duration.zero : const Duration(milliseconds: 300),
          curve: const Cubic(.2, .7, .2, 1),
          builder: (context, s, _) => CustomPaint(painter: _LevelPainter(s, color, dim, glow)),
        ),
      ),
    );
  }
}

class _Shape {
  const _Shape(this.fill, this.bars, this.glow);
  final double fill;
  final double bars;
  final double glow;

  _Shape lerp(_Shape b, double t) =>
      _Shape(fill + (b.fill - fill) * t, bars + (b.bars - bars) * t, glow + (b.glow - glow) * t);

  @override
  bool operator ==(Object o) => o is _Shape && o.fill == fill && o.bars == bars && o.glow == glow;
  @override
  int get hashCode => Object.hash(fill, bars, glow);
}

class _ShapeTween extends Tween<_Shape> {
  _ShapeTween({super.end});
  @override
  _Shape lerp(double t) => (begin ?? end!).lerp(end!, t);
}

class _LevelPainter extends CustomPainter {
  _LevelPainter(this.s, this.color, this.dim, this.glow);
  final _Shape s;
  final Color color;
  final Color dim;
  final bool glow;

  @override
  void paint(Canvas canvas, Size size) {
    final r = size.width / 2;
    final c = Offset(r, r);
    final w = math.max(1.5, size.width / 7);
    final inner = r - w / 2;
    if (glow && s.glow > 0) {
      canvas.drawCircle(
        c,
        r * 1.1,
        Paint()
          ..color = color.withValues(alpha: .55 * s.glow)
          ..maskFilter = MaskFilter.blur(BlurStyle.normal, r * .9),
      );
    }
    canvas.drawCircle(
      c,
      inner,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w
        ..color = Color.lerp(color, dim, s.bars)!,
    );
    if (s.fill > 0) {
      // from the bottom, clockwise: half = the left half, all = the whole disc
      canvas.drawArc(
        Rect.fromCircle(center: c, radius: s.fill >= .999 ? r : inner),
        math.pi / 2,
        2 * math.pi * s.fill,
        true,
        Paint()..color = color,
      );
    }
    if (s.bars > 0) {
      final bar = Paint()
        ..color = dim.withValues(alpha: dim.a * s.bars)
        ..strokeWidth = w
        ..strokeCap = StrokeCap.butt;
      canvas.drawLine(Offset(r - r * .32, r * .52), Offset(r - r * .32, r * 1.48), bar);
      canvas.drawLine(Offset(r + r * .32, r * .52), Offset(r + r * .32, r * 1.48), bar);
    }
  }

  @override
  bool shouldRepaint(_LevelPainter old) => old.s != s || old.color != color || old.dim != dim || old.glow != glow;
}
