/// The live world map behind the main window: land as a field of dots, lit as the world is right now (warm by
/// day, indigo at night, an amber band at dusk and dawn), with your servers on it and the line of the current
/// connection.
///
/// Cost: the map is drawn once into an image (a few tens of milliseconds) and then only copied. It is redrawn when
/// the size or theme changes and every 5 minutes while the window is on screen (the terminator moves about 1.25
/// degrees in that time); a hidden window draws nothing. The markers are a separate, cheap layer that repaints only
/// when the servers or the connection change: the line draws in (240 ms), and a light runs along it while connecting.
library;

import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import 'world.dart';
import 'world_data.dart';

/// A server on the map.
class MapPin {
  const MapPin(this.name, this.lat, this.lon, {this.active = false, this.connecting = false, this.grade = 'none'});
  final String name;
  final double lat, lon;
  final bool active, connecting;
  final String grade;
}

/// The map's box inside [size]: full width, the WebView map's aspect, centred a little above the middle.
Rect mapBox(Size size) {
  final aspect = landCols / landRows / 1.24;
  var w = size.width, h = w / aspect;
  if (h > size.height * 1.15) {
    h = size.height * 1.15;
    w = h * aspect;
  }
  return Rect.fromLTWH((size.width - w) / 2, (size.height - h) * .42, w, h);
}

class WorldMap extends StatefulWidget {
  const WorldMap({super.key, this.pins = const [], this.home, this.protected = false, this.sweep = 1, this.now});
  final List<MapPin> pins;

  /// Where this PC is (the exit-IP lookup's home, or the time zone's longitude).
  final (double, double)? home;

  /// The connection line is drawn sealed (green) while protected.
  final bool protected;

  /// 0..1: the daylight sweeping in (the splash); 1 = as it is now.
  final double sweep;

  /// The clock (tests and goldens pass a fixed one).
  final DateTime Function()? now;

  @override
  State<WorldMap> createState() => _WorldMapState();
}

class _WorldMapState extends State<WorldMap> with TickerProviderStateMixin {
  ui.Image? _base, _veil;

  /// The connection line draws in when the connection changes (240 ms); while connecting, a light runs along it.
  late final _arc = AnimationController(vsync: this, duration: const Duration(milliseconds: 240), value: 1);
  late final _run = AnimationController(vsync: this, duration: const Duration(milliseconds: 1600));
  String? _line;
  String _key = '';
  Timer? _tick;
  var _building = false;

  DateTime get _now => (widget.now ?? DateTime.now)();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final visible = TickerMode.valuesOf(context).enabled;
    if (visible && _tick == null) {
      _tick = Timer.periodic(const Duration(minutes: 5), (_) => setState(() => _key = ''));
      _key = ''; // back on screen: the sun has moved
    } else if (!visible) {
      _tick?.cancel();
      _tick = null;
    }
  }

  @override
  void didUpdateWidget(WorldMap old) {
    super.didUpdateWidget(old);
    _syncLine();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncLine());
  }

  void _syncLine() {
    if (!mounted) return;
    final still = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    final a = widget.pins.where((p) => p.active || p.connecting).firstOrNull;
    final key = a == null ? null : '${a.name} ${a.active}';
    if (key != _line) {
      _line = key;
      if (a != null && !still) {
        _arc.forward(from: 0);
      } else {
        _arc.value = 1;
      }
    }
    if (a != null && a.connecting && !still) {
      if (!_run.isAnimating) _run.repeat();
    } else if (_run.isAnimating) {
      _run.stop();
    }
  }

  @override
  void dispose() {
    _arc.dispose();
    _run.dispose();
    _tick?.cancel();
    _base?.dispose();
    _veil?.dispose();
    super.dispose();
  }

  Future<void> _build(Size size, double dpr, NbColors c) async {
    final bucket = _now.millisecondsSinceEpoch ~/ 300000;
    final key = '${size.width.round()}x${size.height.round()}@$dpr ${c.isDark} $bucket';
    if (key == _key || _building || size.isEmpty) return;
    _building = true;
    try {
      final sun = subsolarPoint(_now);
      final base = await _drawBase(size, dpr, c, sun);
      final veil = await _drawVeil(size, c, sun);
      if (!mounted) {
        base.dispose();
        veil.dispose();
        return;
      }
      setState(() {
        _base?.dispose();
        _veil?.dispose();
        _base = base;
        _veil = veil;
        _key = key;
      });
    } finally {
      _building = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final dpr = MediaQuery.devicePixelRatioOf(context);
    return LayoutBuilder(
      builder: (context, box) {
        final size = box.biggest;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) unawaited(_build(size, dpr, c));
        });
        final sun = subsolarPoint(_now);
        return RepaintBoundary(
          child: CustomPaint(
            size: size,
            painter: _MapPainter(_base, _veil, widget.sweep),
            foregroundPainter: _PinsPainter(widget.pins, widget.home, widget.protected, c, sun, _arc, _run),
          ),
        );
      },
    );
  }
}

/// The land dots, coloured by the light over each one, faded at the top and bottom edge.
Future<ui.Image> _drawBase(Size size, double dpr, NbColors c, (double, double) sun) {
  final rec = ui.PictureRecorder();
  final canvas = Canvas(rec)..scale(dpr);
  final b = mapBox(size);
  final dark = c.isDark;
  // the atmosphere: a wide, very soft warm light behind the map, so it melts into the window
  final sky = Paint()
    ..shader = ui.Gradient.radial(b.center.translate(0, -b.height * .08), math.max(b.width * .62, b.height * 1.05), [
      c.orange.withValues(alpha: dark ? .07 : .045),
      c.orange.withValues(alpha: 0),
    ]);
  canvas.drawRect(Offset.zero & size, sky);
  // the graticule, very faint
  final grid = Paint()
    ..color = (dark ? const Color(0xFFD6C6D0) : const Color(0xFF3A4054)).withValues(alpha: dark ? .05 : .07)
    ..strokeWidth = 1;
  for (var lo = -150; lo <= 180; lo += 30) {
    final x = b.left + (lo + 180) / 360 * b.width;
    canvas.drawLine(Offset(x, b.top + b.height * .08), Offset(x, b.bottom - b.height * .06), grid);
  }
  final base = dark ? const Color(0xFFD6C6D0) : const Color(0xFF3A4054);
  final dayTint = dark ? const Color(0xFFFFCE96) : const Color(0xFFFFAA5A);
  final nightTint = dark ? const Color(0xFF5C70D2) : const Color(0xFF2C3A80);
  const duskTint = Color(0xFFFF9646);
  final an = dark ? .58 : .46, ad = dark ? .16 : .08, at = dark ? .28 : .24;
  final pitch = math.max(2.6, b.width / 300);
  final nx = (b.width / pitch).floor(), ny = (b.height / pitch).floor();
  final px = b.width / nx, py = b.height / ny;
  final dot = Paint();
  for (var j = 0; j < ny; j++) {
    final v = (j + .5) / ny;
    final fade = smoothstep(v / .16) * smoothstep((1 - v) / .10);
    if (fade <= .01) continue;
    final lat = mapLat0 - v * mapLatSpan;
    for (var i = 0; i < nx; i++) {
      final u = (i + .5) / nx;
      final f = landAt(u * landCols, v * landRows);
      if (f < .38) continue;
      final rim = f < .62;
      final lon = -180 + u * 360;
      final l = daylight(solarAltitude(lat, lon, sun));
      final t = l.dusk * at;
      final a = math.max(math.max(l.night * an, (1 - l.night) * ad), t);
      final tint = t >= l.night * an && t >= (1 - l.night) * ad ? duskTint : (l.night > .5 ? nightTint : dayTint);
      final alpha = (rim ? .62 : .26 + ((i * 7 + j * 13) % 5) * .012) * fade;
      dot.color = Color.lerp(base, tint, (a * 1.6).clamp(0.0, 1.0))!.withValues(alpha: alpha);
      final r = math.min(px, py) * (rim ? .30 : .40) * (.55 + .45 * fade);
      canvas.drawCircle(Offset(b.left + (i + .5) * px, b.top + (j + .5) * py), r, dot);
    }
  }
  // where the sun stands, a soft warm spot
  final (sLat, sLon) = sun;
  if (sLat <= mapLat0 && sLat >= mapLat0 - mapLatSpan) {
    final (x, y) = project(sLat, sLon, b.width, b.height);
    final p = Offset(b.left + x, b.top + y), r = b.height * .42;
    canvas.drawCircle(p, r, Paint()
      ..shader = ui.Gradient.radial(p, r, [
        const Color(0xFFFFC478).withValues(alpha: dark ? .12 : .09),
        const Color(0xFFFFC478).withValues(alpha: 0),
      ]));
  }
  final pic = rec.endRecording();
  return pic.toImage((size.width * dpr).ceil(), (size.height * dpr).ceil()).whenComplete(pic.dispose);
}

/// The night side and the twilight band over the whole map, oceans too: a small image (192 px wide), scaled up.
Future<ui.Image> _drawVeil(Size size, NbColors c, (double, double) sun) {
  final b = mapBox(size);
  const w = 192;
  final h = math.max(24, (w * b.height / b.width).round());
  final px = Uint8List(w * h * 4);
  final dark = c.isDark;
  final night = dark ? const [92, 112, 210] : const [44, 58, 128];
  const dusk = [255, 150, 70];
  final an = dark ? .16 : .12, at = .10;
  for (var y = 0; y < h; y++) {
    final v = (y + .5) / h;
    final lat = mapLat0 - v * mapLatSpan;
    final fade = smoothstep(v / .16) * smoothstep((1 - v) / .10);
    for (var x = 0; x < w; x++) {
      final lon = -180 + (x + .5) / w * 360;
      final l = daylight(solarAltitude(lat, lon, sun));
      final t = smoothstep(l.dusk) * at;
      final a = math.max(l.night * an, t) * fade;
      final pick = t >= l.night * an ? dusk : night;
      final k = (y * w + x) * 4;
      // premultiplied: Skia reads these pixels as colour times alpha
      px[k] = (pick[0] * a).round();
      px[k + 1] = (pick[1] * a).round();
      px[k + 2] = (pick[2] * a).round();
      px[k + 3] = (a * 255).round();
    }
  }
  final done = Completer<ui.Image>();
  ui.decodeImageFromPixels(px, w, h, ui.PixelFormat.rgba8888, done.complete);
  return done.future;
}

class _MapPainter extends CustomPainter {
  _MapPainter(this.base, this.veil, this.sweep);
  final ui.Image? base, veil;
  final double sweep;

  @override
  void paint(Canvas canvas, Size size) {
    final b = mapBox(size);
    if (veil != null) {
      final src = Rect.fromLTWH(0, 0, veil!.width.toDouble(), veil!.height.toDouble());
      final p = Paint()..filterQuality = FilterQuality.medium;
      // the splash: the daylight sweeps in from the east (the veil slides one map width into place)
      final dx = (1 - sweep) * b.width;
      canvas.save();
      canvas.clipRect(b);
      canvas.drawImageRect(veil!, src, b.shift(Offset(dx, 0)), p);
      if (dx > 0) canvas.drawImageRect(veil!, src, b.shift(Offset(dx - b.width, 0)), p);
      canvas.restore();
    }
    if (base != null) {
      canvas.drawImageRect(base!, Rect.fromLTWH(0, 0, base!.width.toDouble(), base!.height.toDouble()),
          Offset.zero & size, Paint()..filterQuality = FilterQuality.low);
    }
  }

  @override
  bool shouldRepaint(_MapPainter o) => o.base != base || o.veil != veil || o.sweep != sweep;
}

class _PinsPainter extends CustomPainter {
  _PinsPainter(this.pins, this.home, this.protected, this.c, this.sun, this.arc, this.run)
    : super(repaint: Listenable.merge([arc, run]));
  final List<MapPin> pins;
  final (double, double)? home;
  final bool protected;
  final NbColors c;
  final (double, double) sun;
  final Animation<double> arc, run;

  Offset _at(Rect b, double lat, double lon) {
    final (x, y) = project(lat, lon, b.width, b.height);
    return Offset(b.left + x, b.top + y);
  }

  @override
  void paint(Canvas canvas, Size size) {
    final b = mapBox(size);
    final active = pins.where((p) => p.active || p.connecting).firstOrNull;
    final h = home;
    if (h != null) {
      final hp = _at(b, h.$1, h.$2);
      if (active != null) {
        final ap = _at(b, active.lat, active.lon);
        final mid = Offset((hp.dx + ap.dx) / 2, math.min(hp.dy, ap.dy) - (hp - ap).distance * .28);
        final path = Path()
          ..moveTo(hp.dx, hp.dy)
          ..quadraticBezierTo(mid.dx, mid.dy, ap.dx, ap.dy);
        final col = protected ? c.sealed : c.amber;
        final metric = path.computeMetrics().firstOrNull;
        final t = Curves.easeOutCubic.transform(arc.value);
        final drawn = metric == null ? path : metric.extractPath(0, metric.length * t);
        canvas.drawPath(drawn, Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 6
          ..color = col.withValues(alpha: .10));
        canvas.drawPath(drawn, Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.6
          ..shader = ui.Gradient.linear(hp, ap, [col.withValues(alpha: .25), col]));
        // connecting: a light runs from this PC to the server
        if (active.connecting && metric != null && run.isAnimating) {
          final at = metric.getTangentForOffset(metric.length * run.value)?.position;
          if (at != null) {
            canvas.drawCircle(at, 9, Paint()
              ..shader = ui.Gradient.radial(at, 9, [col.withValues(alpha: .7), col.withValues(alpha: 0)]));
          }
        }
      }
      canvas.drawCircle(hp, 3.5, Paint()..color = c.text.withValues(alpha: .85));
      canvas.drawCircle(hp, 7, Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = c.text.withValues(alpha: .35));
    }
    for (final p in pins) {
      final o = _at(b, p.lat, p.lon);
      final col = p.active
          ? c.sealed
          : p.connecting
          ? c.amber
          : switch (p.grade) {
              'fast' => c.sealed.withValues(alpha: .8),
              'fair' => c.amber.withValues(alpha: .8),
              'slow' => c.blocked.withValues(alpha: .8),
              _ => c.dim,
            };
      if (p.active || p.connecting) {
        canvas.drawCircle(o, 14, Paint()
          ..shader = ui.Gradient.radial(o, 14, [col.withValues(alpha: .45), col.withValues(alpha: 0)]));
      }
      canvas.drawCircle(o, p.active ? 4.5 : 3.2, Paint()..color = col);
      canvas.drawCircle(o, p.active ? 4.5 : 3.2, Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = c.bg.withValues(alpha: .8));
    }
  }

  @override
  bool shouldRepaint(_PinsPainter o) =>
      o.protected != protected || o.c != c || o.home != home || !_samePins(o.pins, pins) || o.arc != arc || o.run != run;

  static bool _samePins(List<MapPin> a, List<MapPin> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      final x = a[i], y = b[i];
      if (x.name != y.name || x.lat != y.lat || x.lon != y.lon || x.active != y.active || x.connecting != y.connecting ||
          x.grade != y.grade) {
        return false;
      }
    }
    return true;
  }
}
