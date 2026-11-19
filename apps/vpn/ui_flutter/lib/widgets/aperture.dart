/// The aperture: NOBAD VPN's connect button and the picture of your protection in one.
///
/// - Not protected: the ring is open: a gap at the top, the colour of the text.
/// - Connecting: an amber arc runs round the ring (the only animation that repeats, and only while connecting).
/// - Protected: the ring springs shut and fills with a soft green light.
/// - Blocked (kill switch holds traffic, no tunnel): the ring is shut in red, with a bar across: nothing passes.
///
/// At rest nothing animates (idle CPU 0). The close and open are a spring (NbSpring.ring); with Windows'
/// animation effects off, every change is immediate.
library;

import 'dart:math' as math;

import 'package:flutter/physics.dart';
import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import '../engine/models.dart';
import 'pressable.dart';

class Aperture extends StatefulWidget {
  const Aperture({super.key, required this.protection, required this.label, this.onTap, this.size = 248, this.hint});
  final Protection protection;

  /// What a press does: "Connect", "Disconnect", "Cancel".
  final String label;
  final VoidCallback? onTap;
  final double size;

  /// Under the verb, quieter: the server it will use.
  final String? hint;

  @override
  State<Aperture> createState() => _ApertureState();
}

class _ApertureState extends State<Aperture> with TickerProviderStateMixin {
  /// 0 = open (gap), 1 = sealed.
  late final _close = AnimationController.unbounded(vsync: this, value: _target);

  /// The running arc while connecting.
  late final _run = AnimationController(vsync: this, duration: const Duration(milliseconds: 1400));

  double get _target => switch (widget.protection) {
    Protection.protected || Protection.blocked => 1,
    Protection.connecting => .55,
    Protection.off => 0,
  };

  bool get _still => MediaQuery.maybeDisableAnimationsOf(context) ?? false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _syncRun();
  }

  @override
  void didUpdateWidget(Aperture old) {
    super.didUpdateWidget(old);
    if (old.protection != widget.protection) {
      if (_still) {
        _close.value = _target;
      } else {
        _close.animateWith(SpringSimulation(NbSpring.ring, _close.value, _target, _close.velocity));
      }
      _syncRun();
    }
  }

  void _syncRun() {
    if (widget.protection == Protection.connecting && !_still) {
      if (!_run.isAnimating) _run.repeat();
    } else {
      _run.stop();
    }
  }

  @override
  void dispose() {
    _close.dispose();
    _run.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final color = switch (widget.protection) {
      Protection.protected => c.sealed,
      Protection.connecting => c.amber,
      Protection.blocked => c.blocked,
      Protection.off => c.text,
    };
    return Pressable(
      onTap: widget.onTap,
      semanticLabel: '${widget.label}${widget.hint == null ? '' : ', ${widget.hint}'}',
      ringRadius: BorderRadius.circular(widget.size),
      builder: (context, s) {
        final lift = s.enabled ? (s.down ? .3 : (s.lit ? 1.0 : 0.0)) : 0.0;
        return SizedBox.square(
          dimension: widget.size,
          child: RepaintBoundary(
            child: TweenAnimationBuilder<double>(
              tween: Tween(end: lift),
              duration: NbMotion.of(context, NbMotion.base),
              curve: NbMotion.curve,
              builder: (context, lift, child) => AnimatedBuilder(
                animation: Listenable.merge([_close, _run]),
                builder: (context, child) => Transform.scale(
                  scale: 1 + .025 * lift - (s.down ? .02 : 0),
                  child: CustomPaint(
                    painter: _AperturePainter(
                      close: _close.value,
                      run: widget.protection == Protection.connecting ? _run.value : null,
                      color: color,
                      track: c.line2,
                      glow: widget.protection == Protection.protected ? c.sealed : null,
                      bar: widget.protection == Protection.blocked,
                      lift: lift,
                      dark: c.isDark,
                    ),
                    child: child,
                  ),
                ),
                child: child,
              ),
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    AnimatedSwitcher(
                      duration: NbMotion.of(context, NbMotion.base),
                      switchInCurve: NbMotion.curve,
                      transitionBuilder: (child, a) => FadeTransition(
                        opacity: a,
                        child: ScaleTransition(scale: Tween(begin: .86, end: 1.0).animate(a), child: child),
                      ),
                      child: Text(widget.label, key: ValueKey(widget.label),
                          style: NbType.label(widget.size < 100 ? NbSize.body : NbSize.title, c.text, height: 1.2)),
                    ),
                    if (widget.hint != null) ...[
                      const SizedBox(height: 4),
                      SizedBox(
                        width: widget.size * .7,
                        child: Text(widget.hint!, textAlign: TextAlign.center, maxLines: 1,
                            overflow: TextOverflow.ellipsis, style: NbType.data(12, c.muted, height: 1.3)),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _AperturePainter extends CustomPainter {
  _AperturePainter({
    required this.close,
    required this.run,
    required this.color,
    required this.track,
    required this.glow,
    required this.bar,
    required this.lift,
    required this.dark,
  });
  final double close;
  final double? run;
  final Color color;
  final Color track;
  final Color? glow;
  final bool bar;
  final double lift;
  final bool dark;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final stroke = size.width * .052;
    final r = size.width / 2 - stroke * 1.4;
    final rect = Rect.fromCircle(center: center, radius: r);

    // the soft light inside a sealed ring
    if (glow != null) {
      final a = (close.clamp(0.0, 1.0)) * (dark ? .30 : .20);
      canvas.drawCircle(center, r, Paint()..shader = RadialGradient(colors: [glow!.withValues(alpha: a), glow!.withValues(alpha: 0)])
          .createShader(rect));
    }
    // the track: where the ring will be
    canvas.drawCircle(center, r, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke * .32
      ..color = track);

    // the ring: open by a gap at the top, the gap closing as `close` goes to 1 (a spring may overshoot a little)
    final gap = (1 - close).clamp(0.0, 1.0) * .62 + .0001; // radians each side of the top
    final start = -math.pi / 2 + gap;
    final sweep = 2 * math.pi - 2 * gap;
    final ring = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = close >= .999 ? StrokeCap.butt : StrokeCap.round
      ..color = color.withValues(alpha: run == null ? (.82 + .18 * lift) : .35);
    canvas.drawArc(rect, start, sweep, false, ring);

    // connecting: a pulse ring breathes out of the lens, and a bright arc runs round
    if (run != null) {
      final k = (run! * 2) % 1;
      canvas.drawCircle(center, r + stroke * (.6 + 1.6 * k), Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke * .35 * (1 - k)
        ..color = color.withValues(alpha: .45 * (1 - k)));
      final head = -math.pi / 2 + run! * 2 * math.pi;
      canvas.drawArc(rect, head, math.pi * .55, false, ring
        ..color = color
        ..strokeCap = StrokeCap.round);
    }
    // the ends of an open ring: two small posts, like the sides of a gate
    if (close < .98 && run == null) {
      final post = Paint()
        ..color = color.withValues(alpha: .9)
        ..strokeWidth = stroke * .32
        ..strokeCap = StrokeCap.round;
      for (final a in [start, start + sweep]) {
        final o = center + Offset(math.cos(a), math.sin(a)) * r;
        final d = Offset(math.cos(a), math.sin(a)) * stroke * 1.05;
        canvas.drawLine(o - d, o + d, post);
      }
    }
    // blocked: a bar across the lens
    if (bar) {
      canvas.drawLine(center + Offset(-r * .42, r * .52), center + Offset(r * .42, r * .52), Paint()
        ..color = color
        ..strokeWidth = stroke * .55
        ..strokeCap = StrokeCap.round);
    }
  }

  @override
  bool shouldRepaint(_AperturePainter o) =>
      o.close != close || o.run != run || o.color != color || o.track != track || o.glow != glow || o.bar != bar ||
      o.lift != lift || o.dark != dark;
}
