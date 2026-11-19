/// Motion that shows what changed, kept cheap: short implicit animations, one controller per moving thing, nothing
/// that runs while the screen is still. With Windows' "Animation effects" off, everything appears at once.
library;

import 'dart:async';

import 'package:flutter/physics.dart';
import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';

bool reduceMotion(BuildContext context) => MediaQuery.maybeDisableAnimationsOf(context) ?? false;

/// Fades and lifts its child in once, after [delay] (a stagger: the n-th result waits n × 22 ms).
class Appear extends StatefulWidget {
  const Appear({super.key, required this.child, this.delay = Duration.zero, this.lift = 6});
  final Widget child;
  final Duration delay;
  final double lift;

  /// The delay for the n-th item of a list: the first dozen stagger, the rest come with the last of them.
  static Duration stagger(int n) => Duration(milliseconds: 14 * (n < 12 ? n : 12));

  @override
  State<Appear> createState() => _AppearState();
}

class _AppearState extends State<Appear> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 200));
  late final _a = CurvedAnimation(parent: _c, curve: NbMotion.curve);
  Timer? _wait;
  var _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    if (reduceMotion(context)) {
      _c.value = 1;
    } else if (widget.delay == Duration.zero) {
      _c.forward();
    } else {
      _wait = Timer(widget.delay, () {
        if (mounted) _c.forward();
      });
    }
  }

  @override
  void dispose() {
    _wait?.cancel();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _a,
    child: widget.child,
    builder: (context, child) => _a.value == 1
        ? child!
        : Opacity(
            opacity: _a.value,
            child: Transform.translate(offset: Offset(0, widget.lift * (1 - _a.value)), child: child),
          ),
  );
}

/// A placeholder block while the first answer is on its way; a soft light passes over it.
class Skeleton extends StatelessWidget {
  const Skeleton({super.key, this.width, this.height = 12, this.radius = NbRadius.key});
  final double? width;
  final double height;
  final Radius radius;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: c.isDark ? const Color(0x12FFFFFF) : const Color(0x0F000000),
        borderRadius: BorderRadius.all(radius),
      ),
    );
  }
}

/// Wraps skeleton blocks with one moving highlight (a single controller for the whole group).
class Shimmer extends StatefulWidget {
  const Shimmer({super.key, required this.child});
  final Widget child;

  @override
  State<Shimmer> createState() => _ShimmerState();
}

class _ShimmerState extends State<Shimmer> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1300));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (reduceMotion(context)) {
      _c.stop();
    } else if (!_c.isAnimating) {
      _c.repeat();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final hi = c.isDark ? const Color(0x22FFFFFF) : const Color(0x88FFFFFF);
    return AnimatedBuilder(
      animation: _c,
      child: widget.child,
      builder: (context, child) => ShaderMask(
        blendMode: BlendMode.srcATop,
        shaderCallback: (r) => LinearGradient(
          begin: Alignment(-1.6 + 3.2 * _c.value, 0),
          end: Alignment(-0.6 + 3.2 * _c.value, 0),
          colors: [const Color(0x00FFFFFF), hi, const Color(0x00FFFFFF)],
        ).createShader(r),
        child: child,
      ),
    );
  }
}

/// Result-shaped placeholders: shown while a search is on its way and nothing is on screen yet.
class SkeletonResults extends StatelessWidget {
  const SkeletonResults({super.key, this.rows = 4});
  final int rows;

  @override
  Widget build(BuildContext context) => Shimmer(
    child: Column(
      children: [
        for (var i = 0; i < rows; i++)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Skeleton(width: 40, height: 40, radius: NbRadius.row),
                const SizedBox(width: 30),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Skeleton(width: 180.0 + 40 * (i % 3), height: 14),
                      const SizedBox(height: 8),
                      Skeleton(width: 260.0 - 30 * (i % 2), height: 10),
                      const SizedBox(height: 10),
                      const Skeleton(height: 10),
                    ],
                  ),
                ),
                const SizedBox(width: 40),
                const Skeleton(width: 60, height: 10),
              ],
            ),
          ),
      ],
    ),
  );
}

/// A spring as a curve (critically damped-ish, a touch of overshoot): panels, the palette, the detail pane.
class SpringCurve extends Curve {
  const SpringCurve({this.damping = .72, this.stiffness = 180});
  final double damping;
  final double stiffness;

  @override
  double transformInternal(double t) {
    final sim = SpringSimulation(
      SpringDescription.withDampingRatio(mass: 1, stiffness: stiffness, ratio: damping),
      0,
      1,
      0,
    );
    // the spring settles in about 0.9 s; the curve's t spans that
    return sim.x(t * .9);
  }
}

/// Hover: the child rises on a spring and leans a little toward the pointer (light parallax). The builder gets
/// the lift (0..1) and the parallax offset for inner content. Nothing runs while the pointer is away.
class HoverLift extends StatefulWidget {
  const HoverLift({super.key, required this.builder, this.parallax = 3});
  final Widget Function(BuildContext context, double lift, Offset parallax) builder;
  final double parallax;

  @override
  State<HoverLift> createState() => _HoverLiftState();
}

class _HoverLiftState extends State<HoverLift> with SingleTickerProviderStateMixin {
  late final _c = AnimationController.unbounded(vsync: this);
  Offset _p = Offset.zero;

  void _to(double v) {
    if (reduceMotion(context)) {
      _c.value = v;
      return;
    }
    _c.animateWith(
      SpringSimulation(
        SpringDescription.withDampingRatio(mass: 1, stiffness: 260, ratio: .7),
        _c.value,
        v,
        _c.velocity,
      ),
    );
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MouseRegion(
    onEnter: (_) => _to(1),
    onExit: (_) {
      _p = Offset.zero;
      _to(0);
    },
    onHover: (e) {
      if (reduceMotion(context)) return;
      final box = context.findRenderObject() as RenderBox?;
      if (box == null || !box.hasSize) return;
      final s = box.size;
      final n = Offset((e.localPosition.dx / s.width - .5) * 2, (e.localPosition.dy / s.height - .5) * 2);
      setState(() => _p = n * widget.parallax);
    },
    child: AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final lift = _c.value.clamp(0, 1.2).toDouble();
        return Transform.translate(offset: Offset(0, -2.5 * lift), child: widget.builder(context, lift, _p * lift));
      },
    ),
  );
}
