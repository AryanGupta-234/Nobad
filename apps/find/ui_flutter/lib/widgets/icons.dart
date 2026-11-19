/// The handful of line icons the UI needs, drawn with a 1.6 px stroke on a 20-unit grid (no icon font).
/// The level glyph is here too: the same four shapes everywhere a work level is shown.
library;

import 'dart:math' as math;

import 'package:flutter/widgets.dart';

enum NbGlyph { search, rings, settings, close, chevron, check, folder, plus, pause, play, copy, external }

class NbIcon extends StatelessWidget {
  const NbIcon(this.glyph, {super.key, this.size = 20, required this.color, this.stroke = 1.6});
  final NbGlyph glyph;
  final double size;
  final Color color;
  final double stroke;

  @override
  Widget build(BuildContext context) => SizedBox.square(
      dimension: size, child: CustomPaint(painter: _IconPainter(glyph, color, stroke)));
}

class _IconPainter extends CustomPainter {
  _IconPainter(this.glyph, this.color, this.stroke);
  final NbGlyph glyph;
  final Color color;
  final double stroke;

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 20;
    canvas.scale(s);
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke / s
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    switch (glyph) {
      case NbGlyph.search:
        canvas.drawCircle(const Offset(8.6, 8.6), 5.4, p);
        canvas.drawLine(const Offset(12.6, 12.6), const Offset(16.6, 16.6), p);
      case NbGlyph.rings:
        // concentric rings with a live centre: "watching your files"
        canvas.drawCircle(const Offset(10, 10), 7, p);
        canvas.drawCircle(const Offset(10, 10), 3.6, p);
        canvas.drawCircle(const Offset(10, 10), 1, p..style = PaintingStyle.fill);
      case NbGlyph.settings:
        // three sliders: settings are levels you set, not machinery
        for (final (y, x) in [(5.0, 12.5), (10.0, 6.5), (15.0, 11.0)]) {
          canvas.drawLine(Offset(3, y), Offset(17, y), p);
          canvas.drawCircle(Offset(x, y), 2.1, Paint()
            ..color = color
            ..style = PaintingStyle.fill);
        }
      case NbGlyph.close:
        canvas.drawLine(const Offset(5.5, 5.5), const Offset(14.5, 14.5), p);
        canvas.drawLine(const Offset(14.5, 5.5), const Offset(5.5, 14.5), p);
      case NbGlyph.chevron:
        canvas.drawPath(Path()..moveTo(6, 8)..lineTo(10, 12)..lineTo(14, 8), p);
      case NbGlyph.check:
        canvas.drawPath(Path()..moveTo(4.5, 10.5)..lineTo(8.3, 14.2)..lineTo(15.5, 6), p);
      case NbGlyph.folder:
        canvas.drawPath(
            Path()
              ..moveTo(3, 6)
              ..lineTo(8, 6)
              ..lineTo(9.6, 7.8)
              ..lineTo(17, 7.8)
              ..lineTo(17, 15.5)
              ..lineTo(3, 15.5)
              ..close(),
            p);
      case NbGlyph.plus:
        canvas.drawLine(const Offset(10, 4.5), const Offset(10, 15.5), p);
        canvas.drawLine(const Offset(4.5, 10), const Offset(15.5, 10), p);
      case NbGlyph.pause:
        canvas.drawLine(const Offset(7.5, 5), const Offset(7.5, 15), p);
        canvas.drawLine(const Offset(12.5, 5), const Offset(12.5, 15), p);
      case NbGlyph.play:
        canvas.drawPath(Path()..moveTo(7, 5)..lineTo(15, 10)..lineTo(7, 15)..close(), p);
      case NbGlyph.copy:
        canvas.drawRRect(RRect.fromLTRBR(7, 7, 16, 16, const Radius.circular(2)), p);
        canvas.drawPath(Path()..moveTo(13, 4)..lineTo(4, 4)..lineTo(4, 13), p);
      case NbGlyph.external:
        canvas.drawPath(Path()..moveTo(11, 4)..lineTo(16, 4)..lineTo(16, 9), p);
        canvas.drawLine(const Offset(16, 4), const Offset(9, 11), p);
        canvas.drawPath(Path()..moveTo(14, 12)..lineTo(14, 16)..lineTo(4, 16)..lineTo(4, 6)..lineTo(8, 6), p);
    }
  }

  @override
  bool shouldRepaint(_IconPainter old) => old.glyph != glyph || old.color != color || old.stroke != stroke;
}

/// The work level as a shape, the same everywhere (rail, status line, Indexing): full = a lit disc,
/// gentle = half filled, light = a ring, paused = a ring with two bars. Colour alone never carries the meaning.
class LevelGlyph extends StatelessWidget {
  const LevelGlyph({super.key, required this.level, required this.color, required this.dim, this.size = 12,
      this.glow = true});
  final String level;
  final Color color;
  final Color dim;
  final double size;
  final bool glow;

  @override
  Widget build(BuildContext context) => Semantics(
        label: const {'full': 'Full speed', 'gentle': 'Gentle', 'light': 'Very light', 'paused': 'Paused'}[level],
        child: SizedBox.square(
            dimension: size, child: CustomPaint(painter: _LevelPainter(level, color, dim, glow))),
      );
}

class _LevelPainter extends CustomPainter {
  _LevelPainter(this.level, this.color, this.dim, this.glow);
  final String level;
  final Color color;
  final Color dim;
  final bool glow;

  @override
  void paint(Canvas canvas, Size size) {
    final r = size.width / 2;
    final c = Offset(r, r);
    final w = math.max(1.5, size.width / 7);
    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w
      ..color = level == 'paused' ? dim : color;
    final fill = Paint()..color = color;
    final inner = r - w / 2;
    switch (level) {
      case 'full':
        if (glow) {
          canvas.drawCircle(c, r * 1.1, Paint()
            ..color = color.withValues(alpha: .55)
            ..maskFilter = MaskFilter.blur(BlurStyle.normal, r * .9));
        }
        canvas.drawCircle(c, r, fill);
      case 'gentle':
        canvas.drawCircle(c, inner, ring);
        canvas.drawArc(Rect.fromCircle(center: c, radius: inner), math.pi / 2, math.pi, true, fill);
      case 'paused':
        canvas.drawCircle(c, inner, ring);
        final bar = Paint()
          ..color = dim
          ..strokeWidth = w
          ..strokeCap = StrokeCap.butt;
        canvas.drawLine(Offset(r - r * .32, r * .52), Offset(r - r * .32, r * 1.48), bar);
        canvas.drawLine(Offset(r + r * .32, r * .52), Offset(r + r * .32, r * 1.48), bar);
      default: // light
        canvas.drawCircle(c, inner, ring);
    }
  }

  @override
  bool shouldRepaint(_LevelPainter old) =>
      old.level != level || old.color != color || old.dim != dim || old.glow != glow;
}
