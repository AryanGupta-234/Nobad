/// The live throughput chart: download as a filled orange area, upload as a quiet line, the newest sample on the
/// right edge with its value. It repaints only when a sample arrives (every 2 s while the window is on screen;
/// the engine sends none while it isn't), plus 240 ms of drawing per sample, so it costs nothing at rest.
library;

import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/widgets.dart';

import '../app/theme/tokens.dart';

import '../app/theme/colors.dart';
import '../app/theme/typography.dart';
import '../engine/models.dart' show rate;
import '../state/vpn_controller.dart';

class ThroughputChart extends StatefulWidget {
  const ThroughputChart({super.key, required this.samples, this.height = 150, this.active = true});
  final Samples samples;
  final double height;

  /// Connected: draw the samples. Not connected: a flat line and a plain sentence instead of zeros.
  final bool active;

  @override
  State<ThroughputChart> createState() => _ThroughputChartState();
}

/// Each new sample draws in: the line slides one step left and its newest segment grows to the new value
/// (240 ms). The first samples draw the whole line from the left. Hidden or with animations off: no motion.
class _ThroughputChartState extends State<ThroughputChart> with SingleTickerProviderStateMixin {
  late final _draw = AnimationController(vsync: this, duration: NbMotion.slow, value: 1);
  int _seen = 0;

  @override
  void initState() {
    super.initState();
    widget.samples.revision.addListener(_sample);
  }

  @override
  void didUpdateWidget(ThroughputChart old) {
    super.didUpdateWidget(old);
    if (old.samples != widget.samples) {
      old.samples.revision.removeListener(_sample);
      widget.samples.revision.addListener(_sample);
    }
  }

  void _sample() {
    final rev = widget.samples.revision.value;
    if (rev == _seen) return;
    _seen = rev;
    if (!mounted) return;
    if (NbMotion.of(context, NbMotion.slow) == Duration.zero || !TickerMode.valuesOf(context).enabled) {
      _draw.value = 1;
    } else {
      _draw.forward(from: 0);
    }
  }

  @override
  void dispose() {
    widget.samples.revision.removeListener(_sample);
    _draw.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final samples = widget.samples;
    return Semantics(
      label: 'Throughput chart',
      value: samples.rx.isEmpty ? 'no data' : 'download ${rate(samples.rx.last)}, upload ${rate(samples.tx.last)}',
      child: SizedBox(
        height: widget.height,
        child: RepaintBoundary(
          child: CustomPaint(
            painter: _ChartPainter(samples, c, widget.active, MediaQuery.textScalerOf(context), _draw),
            size: Size.infinite,
          ),
        ),
      ),
    );
  }
}

class _ChartPainter extends CustomPainter {
  _ChartPainter(this.s, this.c, this.active, this.scaler, this.draw)
    : super(repaint: Listenable.merge([s.revision, draw]));
  final Samples s;
  final NbColors c;
  final bool active;
  final TextScaler scaler;

  /// 0..1: how far the newest sample has drawn in.
  final Animation<double> draw;

  /// A round top for the scale: 1, 2, 5 x 10^n bits per second.
  static double niceTop(double v) {
    if (v <= 0) return 1e6;
    final e = math.pow(10, (math.log(v) / math.ln10).floor()).toDouble();
    for (final m in [1.0, 2.0, 5.0, 10.0]) {
      if (v <= m * e) return m * e;
    }
    return 10 * e;
  }

  @override
  void paint(Canvas canvas, Size size) {
    const labelW = 64.0;
    final plot = Rect.fromLTWH(0, 10, size.width - labelW, size.height - 20);
    final grid = Paint()
      ..color = c.line
      ..strokeWidth = 1;
    for (var i = 0; i <= 2; i++) {
      final y = plot.top + plot.height * i / 2;
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), grid);
    }
    final top = niceTop(s.peak * 1.1);
    _label(canvas, rate(top), Offset(plot.right + 10, plot.top - 7), c.dim);
    _label(canvas, '0', Offset(plot.right + 10, plot.bottom - 7), c.dim);

    final n = s.rx.length;
    if (!active || n < 2) {
      _label(canvas, active ? 'Measuring…' : 'Connect to see live throughput', Offset(plot.left, plot.center.dy - 9),
          c.muted, size: 13, mono: false);
      return;
    }
    final step = plot.width / (s.capacity - 1);
    final t = Curves.easeOutCubic.transform(draw.value);
    // the line slides in by the part of a step the newest sample hasn't drawn yet
    final shift = (1 - t) * step;
    Offset pt(int i, double v) =>
        Offset(plot.right - (n - 1 - i) * step + shift, plot.bottom - (v / top).clamp(0, 1) * plot.height);
    Path smooth(List<double> vs) {
      final p = Path()..moveTo(pt(0, vs[0]).dx, pt(0, vs[0]).dy);
      for (var i = 1; i < vs.length; i++) {
        final a = pt(i - 1, vs[i - 1]), b = pt(i, vs[i]);
        final mx = (a.dx + b.dx) / 2;
        p.cubicTo(mx, a.dy, mx, b.dy, b.dx, b.dy);
      }
      return p;
    }

    final rx = s.rx.toList(), tx = s.tx.toList();
    // the newest segment grows from the previous value to the new one
    rx[n - 1] = rx[n - 2] + (rx[n - 1] - rx[n - 2]) * t;
    tx[n - 1] = tx[n - 2] + (tx[n - 1] - tx[n - 2]) * t;
    final line = smooth(rx);
    final area = Path.from(line)
      ..lineTo(pt(n - 1, 0).dx, plot.bottom)
      ..lineTo(pt(0, 0).dx, plot.bottom)
      ..close();
    canvas.save();
    canvas.clipRect(plot.inflate(2));
    canvas.drawPath(area, Paint()
      ..shader = ui.Gradient.linear(plot.topCenter, plot.bottomCenter, [c.orangeA(c.isDark ? .34 : .24), c.orangeA(0)]));
    canvas.drawPath(line, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..strokeJoin = StrokeJoin.round
      ..color = c.orange);
    canvas.drawPath(smooth(tx), Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4
      ..color = c.muted);
    canvas.restore();
    final head = pt(n - 1, rx.last);
    canvas.drawCircle(head, 4.5, Paint()..color = c.orange);
    canvas.drawCircle(head, 9, Paint()..color = c.orangeA(.18));
  }

  void _label(Canvas canvas, String text, Offset at, Color color, {double size = 11, bool mono = true}) {
    final tp = TextPainter(
      text: TextSpan(text: text, style: mono ? NbType.data(size, color) : NbType.text(size, color)),
      textDirection: TextDirection.ltr,
      textScaler: scaler,
    )..layout();
    tp.paint(canvas, at);
    tp.dispose();
  }

  @override
  bool shouldRepaint(_ChartPainter o) => o.s != s || o.c != c || o.active != active || o.draw != draw;
}
