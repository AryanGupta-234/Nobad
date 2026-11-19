/// Frosted spatial glass: the backdrop and the three layers that float over it.
///
/// - [Backdrop]: the window's deep (or pale) base with two soft glows, painted once into its own layer. Over the
///   Windows Mica system backdrop (composited by Windows, free for this process) it is translucent.
/// - [Glass]: a floating layer with continuous (superellipse) corners, a translucent fill, a 1 px light rim on the
///   top edge fading down the sides, and a soft large shadow. Real blur ([GlassLevel.blur]) only for dialogs,
///   which float over content. Measured (docs/measurements.md): a blurred palette cost 40-135 MB at 1080p while
///   only the still backdrop was behind it, so the palette, the detail pane and the cards take their frost from
///   Windows' Mica, the fill and the rim instead.
library;

import 'dart:ui' as ui;

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';

enum GlassLevel {
  /// Results and tiles on the backdrop: fill and rim, no blur, a small shadow.
  card,

  /// Floating panels (the dock, the detail pane): stronger fill, larger shadow.
  panel,

  /// The search palette and popovers: real blur behind them.
  blur,
}

class Backdrop extends StatelessWidget {
  const Backdrop({super.key});

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return RepaintBoundary(
      child: CustomPaint(painter: _BackdropPainter(c), size: Size.infinite),
    );
  }
}

class _BackdropPainter extends CustomPainter {
  _BackdropPainter(this.c);
  final NbColors c;

  @override
  void paint(Canvas canvas, Size size) {
    final r = Offset.zero & size;
    canvas.drawRect(r, Paint()..color = c.canvas);
    final big = size.longestSide;
    // soft coloured light behind the glass (like a macOS wallpaper seen through frosted panes): the NOBAD orange
    // high on the left, a magenta in the middle, an indigo low on the right. Painted once into its own layer.
    void glow(double x, double y, double radius, Color col) => canvas.drawRect(
      r,
      Paint()
        ..shader = ui.Gradient.radial(Offset(size.width * x, size.height * y), big * radius, [
          col,
          col.withValues(alpha: col.a * .45),
          col.withValues(alpha: 0),
        ], const [0, .45, 1]),
    );
    glow(.10, .05, .55, c.glowWarm);
    glow(.55, .55, .45, c.glowMagenta);
    glow(.95, 1.0, .60, c.glowCool);
    glow(.85, .05, .30, c.glowWarm.withValues(alpha: c.glowWarm.a * .6));
  }

  @override
  bool shouldRepaint(_BackdropPainter old) => old.c != c;
}

class Glass extends StatelessWidget {
  /// Measurement switch: NOBAD_FIND_NO_BLUR=1 draws the blurred layers without blur.
  static bool noBlur = false;

  const Glass({
    super.key,
    required this.child,
    this.level = GlassLevel.card,
    this.radius = 18,
    this.padding,
    this.fill,
    this.rim,
    this.lift = 0,
  });

  final Widget child;
  final GlassLevel level;
  final double radius;
  final EdgeInsetsGeometry? padding;

  /// Overrides the level's fill (a selected card's warm tint).
  final Color? fill;

  /// Overrides the rim (a selected card's orange edge).
  final Color? rim;

  /// 0..1: how far it has risen (hover); deepens the shadow.
  final double lift;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final shape = RoundedSuperellipseBorder(borderRadius: BorderRadius.circular(radius));
    final base =
        fill ??
        switch (level) {
          GlassLevel.card => c.card,
          GlassLevel.panel => c.panel,
          GlassLevel.blur => c.panel,
        };
    final shadow = switch (level) {
      GlassLevel.card => [
        BoxShadow(
          color: c.float.withValues(alpha: c.float.a * (.22 + .5 * lift)),
          blurRadius: 8 + 10 * lift,
          offset: Offset(0, 2 + 4 * lift),
          spreadRadius: -4,
        ),
      ],
      _ => [
        BoxShadow(
          color: c.float.withValues(alpha: c.float.a * .45),
          blurRadius: 24,
          offset: const Offset(0, 6),
          spreadRadius: -10,
        ),
      ],
    };
    Widget body = CustomPaint(
      painter: _FrostPainter(radius, c),
      foregroundPainter: _RimPainter(radius, rim, c),
      child: Padding(padding: padding ?? EdgeInsets.zero, child: child),
    );
    if (level == GlassLevel.blur && !Glass.noBlur) {
      body = ClipRSuperellipse(
        borderRadius: BorderRadius.circular(radius),
        child: BackdropFilter(
          filter: ui.ImageFilter.blur(sigmaX: 18, sigmaY: 18, tileMode: TileMode.decal),
          child: ColoredBox(color: base, child: body),
        ),
      );
    } else {
      body = DecoratedBox(
        decoration: ShapeDecoration(shape: shape, color: base),
        child: body,
      );
    }
    return CustomPaint(painter: _OuterShadow(radius, shadow.first), child: body);
  }
}

/// A soft shadow drawn only outside the shape: translucent glass must not show its own shadow through itself.
class _OuterShadow extends CustomPainter {
  _OuterShadow(this.radius, this.shadow);
  final double radius;
  final BoxShadow shadow;

  @override
  void paint(Canvas canvas, Size size) {
    final shape = RSuperellipse.fromRectAndRadius(Offset.zero & size, Radius.circular(radius));
    final outside = Path()
      ..fillType = PathFillType.evenOdd
      ..addRect((Offset.zero & size).inflate(shadow.blurRadius * 2 + 40))
      ..addRSuperellipse(shape);
    canvas.save();
    canvas.clipPath(outside);
    final r = RSuperellipse.fromRectAndRadius(
      (Offset.zero & size).shift(shadow.offset).inflate(shadow.spreadRadius),
      Radius.circular(radius),
    );
    canvas.drawRSuperellipse(r, shadow.toPaint());
    canvas.restore();
  }

  @override
  bool shouldRepaint(_OuterShadow old) => old.radius != radius || old.shadow != shadow;
}

/// What makes a translucent layer read as frosted glass, without blurring anything live (no per-frame cost): a
/// faint white sheen falling from the top edge, and a fixed fine grain (the same dots every paint, so nothing
/// shimmers).
class _FrostPainter extends CustomPainter {
  _FrostPainter(this.radius, this.c);
  final double radius;
  final NbColors c;

  static final List<Offset> _grain = () {
    // a fixed 96 x 96 tile of 260 dots from a small LCG: deterministic, so goldens stay stable
    var x = 0x2545F491;
    double next() {
      x = (x * 1103515245 + 12345) & 0x7fffffff;
      return (x % 9600) / 100.0;
    }
    return [for (var i = 0; i < 260; i++) Offset(next(), next())];
  }();

  @override
  void paint(Canvas canvas, Size size) {
    final shape = RSuperellipse.fromRectAndRadius(Offset.zero & size, Radius.circular(radius));
    canvas.save();
    canvas.clipRSuperellipse(shape);
    canvas.drawRect(
      Offset.zero & size,
      Paint()
        ..shader = ui.Gradient.linear(Offset.zero, Offset(0, size.height.clamp(1, 220)), [
          c.sheen,
          c.sheen.withValues(alpha: 0),
        ]),
    );
    final dot = Paint()
      ..color = c.grain
      ..strokeWidth = 1
      ..strokeCap = StrokeCap.square;
    for (var ty = 0.0; ty < size.height; ty += 96) {
      for (var tx = 0.0; tx < size.width; tx += 96) {
        canvas.drawPoints(ui.PointMode.points, [for (final g in _grain) g.translate(tx, ty)], dot);
      }
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_FrostPainter old) => old.radius != radius || old.c != c;
}

/// The fine rim: bright on the top edge, fading to almost nothing at the bottom, like light on a glass pane.
class _RimPainter extends CustomPainter {
  _RimPainter(this.radius, this.rim, this.c);
  final double radius;
  final Color? rim;
  final NbColors c;

  @override
  void paint(Canvas canvas, Size size) {
    final r = RSuperellipse.fromRectAndRadius((Offset.zero & size).deflate(.5), Radius.circular(radius));
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = rim == null ? 1 : 1.2;
    if (rim != null) {
      p.color = rim!;
    } else {
      p.shader = ui.Gradient.linear(Offset.zero, Offset(0, size.height), [c.rimLight, c.rimShade], [0, .55]);
    }
    canvas.drawRSuperellipse(r, p);
  }

  @override
  bool shouldRepaint(_RimPainter old) => old.radius != radius || old.rim != rim || old.c != c;
}
