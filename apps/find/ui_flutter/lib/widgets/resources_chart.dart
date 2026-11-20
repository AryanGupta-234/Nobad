/// NOBAD Find's own processor and memory use over the last 5 minutes (150 governor samples, 2 s apart).
///
/// Processor: the orange line with a soft fill, on its own % scale (top label). Memory: a dashed quiet line on its
/// own scale. The newest sample is always at the right edge. Hover reads out one sample; the caption says what
/// the lines are, so colour is never the only key.
library;

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/typography.dart';
import '../engine/models/format.dart';
import '../engine/models/status.dart';
import 'motion.dart';

class ResourcesChart extends StatefulWidget {
  const ResourcesChart({super.key, required this.history, this.height = 120});
  final List<HistoryPoint> history;
  final double height;

  static const slots = 150;

  @override
  State<ResourcesChart> createState() => _ResourcesChartState();
}

class _ResourcesChartState extends State<ResourcesChart> {
  int _hover = -1;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final h = widget.history;
    final n = h.length;
    final i = _hover >= 0 && _hover < n ? _hover : n - 1;
    final x = n == 0 ? null : h[i];
    final when = i == n - 1 ? 'now' : '${span((n - 1 - i) * 2).replaceFirst('about ', '')} ago';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          label: 'NOBAD Find processor and memory use over the last 5 minutes',
          image: true,
          child: MouseRegion(
            onHover: (e) {
              if (n < 2) return;
              final box = context.findRenderObject() as RenderBox?;
              final w = box?.size.width ?? 1;
              final slot = (e.localPosition.dx / w * (ResourcesChart.slots - 1)).round();
              setState(() => _hover = (slot - (ResourcesChart.slots - n)).clamp(0, n - 1));
            },
            onExit: (_) => setState(() => _hover = -1),
            child: SizedBox(
              height: widget.height,
              // a new sample slides the lines one step left instead of jumping
              child: TweenAnimationBuilder<double>(
                key: ValueKey(n == 0 ? 0.0 : h.last.t),
                tween: Tween(begin: reduceMotion(context) || n < 2 ? 0 : 1, end: 0),
                duration: const Duration(milliseconds: 400),
                curve: Curves.easeOutCubic,
                builder: (context, shift, _) =>
                    CustomPaint(painter: _ChartPainter(h, i, c, NbType.data(10, c.dim), shift), size: Size.infinite),
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        if (n < 2)
          Text('Collecting the first readings…', style: NbType.text(NbSize.small, c.dim))
        else
          Row(
            children: [
              _Key(solid: true, color: c.orange),
              Text('Processor ${pct(x!.findCpu)}', style: NbType.data(NbSize.caption, c.muted)),
              const SizedBox(width: 16),
              _Key(solid: false, color: c.dim),
              Text('Memory ${mb(x.findMb)}', style: NbType.data(NbSize.caption, c.muted)),
              const Spacer(),
              Text('$when · last 5 minutes', style: NbType.data(NbSize.caption, c.dim)),
            ],
          ),
      ],
    );
  }
}

class _Key extends StatelessWidget {
  const _Key({required this.solid, required this.color});
  final bool solid;
  final Color color;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(right: 6),
    child: CustomPaint(size: const Size(14, 2), painter: _KeyPainter(solid, color)),
  );
}

class _KeyPainter extends CustomPainter {
  _KeyPainter(this.solid, this.color);
  final bool solid;
  final Color color;
  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..strokeWidth = 2;
    if (solid) {
      canvas.drawLine(Offset(0, size.height / 2), Offset(size.width, size.height / 2), p);
    } else {
      canvas.drawLine(Offset(0, size.height / 2), Offset(5, size.height / 2), p);
      canvas.drawLine(Offset(8, size.height / 2), Offset(13, size.height / 2), p);
    }
  }

  @override
  bool shouldRepaint(_KeyPainter old) => old.color != color || old.solid != solid;
}

class _ChartPainter extends CustomPainter {
  _ChartPainter(this.h, this.focus, this.c, this.labelStyle, this.shift);
  final List<HistoryPoint> h;
  final int focus;
  final NbColors c;
  final TextStyle labelStyle;

  /// 1 → 0 while a new sample comes in: the lines sit one step to the right and slide into place.
  final double shift;

  @override
  void paint(Canvas canvas, Size size) {
    const padT = 8.0, padB = 6.0;
    final w = size.width, H = size.height - padT - padB;
    final n = h.length;
    final grid = Paint()
      ..color = c.line
      ..strokeWidth = 1;
    for (final f in [0.0, .5, 1.0]) {
      final y = (padT + H * f).roundToDouble() + .5;
      canvas.drawLine(Offset(0, y), Offset(w, y), grid);
    }
    var maxCpu = 10.0;
    var maxMb = 1.0;
    for (final p in h) {
      if (p.findCpu > maxCpu) maxCpu = p.findCpu;
      if (p.findMb > maxMb) maxMb = p.findMb;
    }
    maxCpu = (maxCpu / 10).ceil() * 10.0;
    maxMb *= 1.1;
    final tp = TextPainter(
      text: TextSpan(text: '${maxCpu.round()}%', style: labelStyle),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, const Offset(4, padT + 3));
    tp.dispose();
    if (n < 2) return;
    final step = w / (ResourcesChart.slots - 1);
    double X(int i) => w - (n - 1 - i) * step + shift * step;
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    double Y(double v, double m) => padT + H - (v / m) * H;

    final mem = Path();
    for (var i = 0; i < n; i++) {
      final o = Offset(X(i), Y(h[i].findMb, maxMb));
      i == 0 ? mem.moveTo(o.dx, o.dy) : mem.lineTo(o.dx, o.dy);
    }
    final memPaint = Paint()
      ..color = c.dim
      ..strokeWidth = 1.25
      ..style = PaintingStyle.stroke;
    for (final m in mem.computeMetrics()) {
      for (var d = 0.0; d < m.length; d += 7) {
        canvas.drawPath(m.extractPath(d, d + 4), memPaint);
      }
    }

    final cpu = Path();
    for (var i = 0; i < n; i++) {
      final o = Offset(X(i), Y(h[i].findCpu, maxCpu));
      i == 0 ? cpu.moveTo(o.dx, o.dy) : cpu.lineTo(o.dx, o.dy);
    }
    final area = Path.from(cpu)
      ..lineTo(X(n - 1), padT + H)
      ..lineTo(X(0), padT + H)
      ..close();
    canvas.drawPath(
      area,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [c.orangeA(c.isDark ? .28 : .18), c.orangeA(0)],
        ).createShader(Rect.fromLTWH(0, padT, w, H)),
    );
    canvas.drawPath(
      cpu,
      Paint()
        ..color = c.orange
        ..strokeWidth = 1.75
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round,
    );

    final fx = X(focus);
    if (focus != n - 1) {
      canvas.drawLine(
        Offset(fx, padT),
        Offset(fx, padT + H),
        Paint()
          ..color = c.line2
          ..strokeWidth = 1,
      );
    }
    canvas.drawCircle(Offset(fx, Y(h[focus].findCpu, maxCpu)), 3.5, Paint()..color = c.orange);
    canvas.restore();
  }

  @override
  bool shouldRepaint(_ChartPainter old) =>
      !identical(old.h, h) || old.focus != focus || old.c != c || old.shift != shift;
}
