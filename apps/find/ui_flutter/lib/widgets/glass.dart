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
    // the NOBAD orange high on the left, a cool indigo low on the right: depth without a picture
    canvas.drawRect(
      r,
      Paint()
        ..shader = ui.Gradient.radial(Offset(size.width * .18, -size.height * .1), big * .75, [
          c.glowWarm,
          c.glowWarm.withValues(alpha: 0),
        ]),
    );
    canvas.drawRect(
      r,
      Paint()
        ..shader = ui.Gradient.radial(Offset(size.width * .92, size.height * 1.05), big * .7, [
          c.glowCool,
          c.glowCool.withValues(alpha: 0),
        ]),
    );
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
    this.radius = 20,
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
          color: c.float.withValues(alpha: c.float.a * (.35 + .65 * lift)),
          blurRadius: 18 + 22 * lift,
          offset: Offset(0, 6 + 10 * lift),
          spreadRadius: -8,
        ),
      ],
      _ => [
        BoxShadow(
          color: c.float.withValues(alpha: c.float.a * .7),
          blurRadius: 56,
          offset: const Offset(0, 14),
          spreadRadius: -18,
        ),
      ],
    };
    Widget body = CustomPaint(
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
