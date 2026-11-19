/// The interactive world map: a vector dot field (crisp at any zoom), lit as the world is right now, with a pin for
/// every server, clustered when close, a frosted tooltip on hover, click to select, double-click (or Connect in the
/// tooltip) to connect, wheel/pinch to zoom, drag to pan, and Fit all. When connected, an arc runs from this PC to
/// the server and the server's pin pulses.
///
/// Cost: the land and the night side are painted (as paths and points, not a bitmap) only when the camera, the size,
/// the theme or the sun's 5-minute step changes; hover only repaints the pins layer. The arc and pulse are the only
/// things that move on their own, only while connected, and they stop when the window is hidden (TickerMode).
library;

import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/gestures.dart';
import 'package:material_ui/material_ui.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import '../widgets/controls.dart';
import '../widgets/icons.dart';
import 'camera.dart';
import 'world.dart';

/// A server on the map. [place] and [endpoint] are for the tooltip; [rtt] the last measured latency.
class MapServer {
  const MapServer({
    required this.name,
    required this.lat,
    required this.lon,
    this.place = '',
    this.endpoint = '',
    this.rtt,
    this.grade = 'none',
    this.active = false,
    this.connecting = false,
  });
  final String name;
  final double lat, lon;
  final String place, endpoint;
  final double? rtt;
  final String grade;
  final bool active, connecting;
}

class MapView extends StatefulWidget {
  const MapView({
    super.key,
    required this.servers,
    this.home,
    this.selected,
    this.status = '',
    this.connected = false,
    this.onSelect,
    this.onConnect,
    this.now,
  });
  final List<MapServer> servers;
  final (double, double)? home;
  final String? selected;

  /// The chip on the map: "Connected · Tokyo, JP · 61 ms".
  final String status;
  final bool connected;
  final ValueChanged<String>? onSelect;
  final ValueChanged<String>? onConnect;
  final DateTime Function()? now;

  @override
  State<MapView> createState() => MapViewState();
}

class MapViewState extends State<MapView> with TickerProviderStateMixin {
  MapCamera camera = MapCamera.world;
  MapCamera? _from, _to;
  late final AnimationController _ease = AnimationController(vsync: this, duration: const Duration(milliseconds: 240))
    ..addListener(_eased);

  void _eased() {
    if (_from != null && _to != null) {
      setState(() => camera = MapCamera.lerp(_from!, _to!, Curves.easeOutCubic.transform(_ease.value)));
    }
  }

  /// The arc drawing in (240 ms), then the pulse and the flow along it, while connected and on screen.
  late final _arc = AnimationController(vsync: this, duration: const Duration(milliseconds: 240), value: 1);
  late final _pulse = AnimationController(vsync: this, duration: const Duration(milliseconds: 2400));
  Size _size = Size.zero;
  PinCluster? _hover;
  Offset? _lastPointer;
  Timer? _sunTick;
  int _sunStep = 0;
  String? _activeKey;
  bool _userMoved = false;
  String? _pickedHere;

  bool get _still => MediaQuery.maybeDisableAnimationsOf(context) ?? false;
  DateTime get _now => (widget.now ?? DateTime.now)();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final visible = TickerMode.valuesOf(context).enabled;
    if (visible && _sunTick == null) {
      _sunStep = _now.millisecondsSinceEpoch ~/ 300000;
      _sunTick = Timer.periodic(const Duration(minutes: 5), (_) => setState(() => _sunStep++));
    } else if (!visible) {
      _sunTick?.cancel();
      _sunTick = null;
    }
    _syncMotion();
  }

  @override
  void didUpdateWidget(MapView oldWidget) {
    super.didUpdateWidget(oldWidget);
    final old = oldWidget;
    final active = widget.servers.where((s) => s.active || s.connecting).firstOrNull;
    final key = active == null ? null : '${active.name} ${active.active}';
    if (key != _activeKey) {
      _activeKey = key;
      if (active != null) {
        if (_still) {
          _arc.value = 1;
        } else {
          _arc.forward(from: 0);
        }
        if (!_userMoved) easeTo(_cameraFor([active]));
      }
    }
    if (widget.selected != old.selected && widget.selected != null) {
      // picked in the list: ease to it. Picked here on the map: stay put (a double-click must find the pin again)
      final s = widget.servers.where((x) => x.name == widget.selected).firstOrNull;
      if (s != null && widget.selected != _pickedHere) _focus(s);
    }
    _pickedHere = null;
    _syncMotion();
  }

  void _syncMotion() {
    final run = widget.connected && !_still && TickerMode.valuesOf(context).enabled;
    if (run && !_pulse.isAnimating) {
      _pulse.repeat();
    } else if (!run && _pulse.isAnimating) {
      _pulse.stop();
    }
  }

  @override
  void dispose() {
    _sunTick?.cancel();
    _ease.dispose();
    _arc.dispose();
    _pulse.dispose();
    super.dispose();
  }

  MapCamera _cameraFor(List<MapServer> s) {
    final pts = [for (final x in s) (x.lat, x.lon), if (widget.home != null && s.any((x) => x.active || x.connecting)) widget.home!];
    return MapCamera.fit(pts, _size, margin: 56);
  }

  /// Ease toward [target] (240 ms; at once with animations off).
  void easeTo(MapCamera target) {
    if (_size.isEmpty) {
      camera = target;
      return;
    }
    final t = target.clamped(_size);
    if (_still) {
      setState(() => camera = t);
      return;
    }
    _from = camera;
    _to = t;
    _ease.forward(from: 0);
  }

  void _focus(MapServer s) {
    final p = camera.toScreen(s.lat, s.lon, _size);
    final inside = (Offset.zero & _size).deflate(40).contains(p);
    if (inside && camera.zoom >= 2) return;
    easeTo(MapCamera(lat: s.lat, lon: s.lon, zoom: math.max(camera.zoom, 2.4)));
  }

  void fitAll() {
    _userMoved = false;
    easeTo(MapCamera.fit([for (final s in widget.servers) (s.lat, s.lon), ?widget.home], _size, margin: 48));
  }

  List<PinCluster> _clusters() => cluster([
    for (final s in widget.servers)
      ScreenPin(s.name, camera.toScreen(s.lat, s.lon, _size), keep: s.active || s.connecting || s.name == widget.selected),
  ], radius: 18);

  MapServer? _server(String name) => widget.servers.where((s) => s.name == name).firstOrNull;

  void _onHover(Offset p) {
    _lastPointer = p;
    final h = hitTest(_clusters(), p);
    if (h?.names.join() != _hover?.names.join()) setState(() => _hover = h);
  }

  void _onTap(Offset p) {
    final h = hitTest(_clusters(), p);
    if (h == null) return;
    if (h.single) {
      _pickedHere = h.names.single;
      widget.onSelect?.call(h.names.single);
    } else {
      _userMoved = true;
      easeTo(MapCamera.fit([for (final n in h.names) if (_server(n) case final s?) (s.lat, s.lon)], _size, margin: 80));
    }
  }

  void _onDoubleTap() {
    final p = _lastPointer;
    if (p == null) return;
    final h = hitTest(_clusters(), p);
    if (h != null && h.single) widget.onConnect?.call(h.names.single);
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return LayoutBuilder(
      builder: (context, box) {
        final size = box.biggest;
        if (size != _size) {
          final first = _size.isEmpty;
          _size = size;
          camera = first ? MapCamera.fit([for (final s in widget.servers) (s.lat, s.lon), ?widget.home], size, margin: 48)
              : camera.clamped(size);
        }
        final clusters = _clusters();
        final sun = subsolarPoint(DateTime.fromMillisecondsSinceEpoch(_sunStep * 300000, isUtc: true));
        final hover = _hover;
        return ClipRRect(
          borderRadius: NbRadius.panelAll,
          child: Stack(
            children: [
              Positioned.fill(
                child: Listener(
                  onPointerSignal: (e) {
                    if (e is PointerScrollEvent) {
                      _userMoved = true;
                      _ease.stop();
                      setState(() => camera = camera.zoomAbout(e.localPosition,
                          camera.zoom * math.pow(1.0015, -e.scrollDelta.dy).toDouble(), size));
                      _onHover(e.localPosition);
                    }
                  },
                  child: MouseRegion(
                    cursor: hover != null ? SystemMouseCursors.click : SystemMouseCursors.grab,
                    onHover: (e) => _onHover(e.localPosition),
                    onExit: (_) => setState(() => _hover = null),
                    child: GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTapUp: (d) => _onTap(d.localPosition),
                      onDoubleTap: _onDoubleTap,
                      onScaleStart: (_) => _ease.stop(),
                      onScaleUpdate: (d) {
                        _userMoved = true;
                        var cam = camera.pan(d.focalPointDelta, size);
                        if (d.scale != 1) cam = cam.zoomAbout(d.localFocalPoint, cam.zoom * (1 + (d.scale - 1) * .08), size);
                        setState(() => camera = cam);
                      },
                      // two layers: the land repaints only when the camera, theme or sun move; the pins on hover,
                      // and every frame of the arc and pulse while connected
                      child: Stack(
                        children: [
                          RepaintBoundary(child: CustomPaint(size: size, painter: _LandPainter(camera, c, sun))),
                          RepaintBoundary(
                            child: CustomPaint(
                          size: size,
                          painter: _PinsPainter(
                            camera: camera,
                            servers: widget.servers,
                            clusters: clusters,
                            home: widget.home,
                            selected: widget.selected,
                            hover: hover,
                            connected: widget.connected,
                            c: c,
                            arc: _arc,
                            pulse: _pulse,
                          ),
                        ),
                      ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              // the map's controls: zoom and fit all
              Positioned(
                right: NbSpace.x2,
                top: NbSpace.x2,
                child: Row(
                  children: [
                    _MapButton(label: 'Zoom out', text: '−', onTap: () => easeTo(camera.zoomAbout(size.center(Offset.zero), camera.zoom / 1.6, size))),
                    const SizedBox(width: 4),
                    _MapButton(label: 'Zoom in', text: '+', onTap: () => easeTo(camera.zoomAbout(size.center(Offset.zero), camera.zoom * 1.6, size))),
                    const SizedBox(width: 4),
                    _MapButton(label: 'Fit all', text: 'Fit all', onTap: fitAll),
                  ],
                ),
              ),
              if (widget.status.isNotEmpty)
                Positioned(
                  left: NbSpace.x2,
                  bottom: NbSpace.x2,
                  child: _Chip(text: widget.status, live: widget.connected),
                ),
              if (hover != null) _tooltip(context, hover, size),
            ],
          ),
        );
      },
    );
  }

  Widget _tooltip(BuildContext context, PinCluster h, Size size) {
    final c = NbColors.of(context);
    const w = 220.0;
    final left = (h.at.dx + 14).clamp(8.0, size.width - w - 8);
    final top = (h.at.dy - 12).clamp(8.0, size.height - 120);
    final servers = [for (final n in h.names) ?_server(n)];
    return Positioned(
      left: left,
      top: top,
      width: w,
      child: MouseRegion(
        onEnter: (_) {},
        child: TweenAnimationBuilder<double>(
          tween: Tween(begin: 0, end: 1),
          duration: NbMotion.of(context, NbMotion.fast),
          builder: (context, v, child) => Opacity(opacity: v, child: Transform.translate(offset: Offset(0, 4 * (1 - v)), child: child)),
          child: Container(
            padding: const EdgeInsets.all(NbSpace.x3),
            decoration: BoxDecoration(
              color: c.surface.withValues(alpha: c.isDark ? .88 : .94),
              borderRadius: NbRadius.rowAll,
              border: Border.all(color: c.orangeA(.35)),
              boxShadow: [BoxShadow(color: c.float, blurRadius: 24, offset: const Offset(0, 8), spreadRadius: -8)],
            ),
            child: servers.length == 1
                ? _one(c, servers.single)
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text('${servers.length} servers here', style: NbType.label(NbSize.body, c.text)),
                      const SizedBox(height: 4),
                      for (final s in servers.take(5)) Text(s.name, style: NbType.data(NbSize.small, c.muted)),
                      const SizedBox(height: 6),
                      Text('Click to zoom in', style: NbType.text(NbSize.caption, c.dim)),
                    ],
                  ),
          ),
        ),
      ),
    );
  }

  Widget _one(NbColors c, MapServer s) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(s.name, style: NbType.label(NbSize.body, c.text)),
      if (s.place.isNotEmpty) Text(s.place, style: NbType.text(NbSize.small, c.muted)),
      const SizedBox(height: 4),
      Text(s.endpoint, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.data(NbSize.caption, c.muted)),
      Text(s.rtt == null ? 'Latency not measured yet' : 'Last ping ${s.rtt!.round()} ms',
          style: NbType.data(NbSize.caption, s.rtt == null ? c.dim : c.text)),
      const SizedBox(height: 8),
      Row(
        children: [
          if (s.active)
            Text('Connected', style: NbType.label(NbSize.small, c.sealed))
          else if (s.connecting)
            Text('Connecting…', style: NbType.label(NbSize.small, c.amber))
          else
            NbButton('Connect', small: true, onPressed: widget.onConnect == null ? null : () => widget.onConnect!(s.name)),
          const Spacer(),
          Text('double-click', style: NbType.text(NbSize.caption, c.dim)),
        ],
      ),
    ],
  );
}

class _MapButton extends StatelessWidget {
  const _MapButton({required this.label, required this.text, required this.onTap});
  final String label, text;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Tooltip(
    message: label,
    child: NbButton(text, small: true, kind: NbButtonKind.ghost, onPressed: onTap),
  );
}

class _Chip extends StatelessWidget {
  const _Chip({required this.text, required this.live});
  final String text;
  final bool live;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: c.surface.withValues(alpha: c.isDark ? .82 : .9),
          borderRadius: NbRadius.pillAll,
          border: Border.all(color: live ? c.sealed.withValues(alpha: .45) : c.line2),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            NbIcon(NbGlyph.globe, size: 14, color: live ? c.sealed : c.muted),
            const SizedBox(width: 6),
            Text(text, style: NbType.label(NbSize.small, c.text)),
          ],
        ),
      ),
    );
  }
}

/// The land as a dot field, each dot coloured by the light over it, and the night side as a vector veil with the
/// twilight band along the terminator.
class _LandPainter extends CustomPainter {
  _LandPainter(this.camera, this.c, this.sun);
  final MapCamera camera;
  final NbColors c;
  final (double, double) sun;

  @override
  void paint(Canvas canvas, Size size) {
    final dark = c.isDark;
    // the night side: from the terminator to the pole that has no sun
    final (sLat, sLon) = sun;
    final night = Path(), line = Path();
    final tanDec = math.tan((sLat.abs() < .1 ? .1 : sLat) * math.pi / 180);
    for (var lon = -180.0; lon <= 180.0; lon += 2) {
      final h = (lon - sLon) * math.pi / 180;
      final lat = math.atan(-math.cos(h) / tanDec) * 180 / math.pi;
      final p = camera.toScreen(lat, lon, size);
      lon == -180 ? line.moveTo(p.dx, p.dy) : line.lineTo(p.dx, p.dy);
    }
    final darkPole = sLat >= 0 ? -90.0 : 90.0;
    night.addPath(line, Offset.zero);
    final e = camera.toScreen(darkPole, 180, size), s = camera.toScreen(darkPole, -180, size);
    night
      ..lineTo(e.dx, e.dy)
      ..lineTo(s.dx, s.dy)
      ..close();
    canvas.drawPath(night, Paint()..color = (dark ? const Color(0xFF5C70D2) : const Color(0xFF2C3A80)).withValues(alpha: dark ? .16 : .10));
    canvas.drawPath(line, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 8
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 5)
      ..color = const Color(0xFFFF9646).withValues(alpha: dark ? .14 : .10));

    // the land dots: sampled on a screen grid, so they stay crisp at any zoom
    final pitch = math.max(4.0, size.width / 230);
    final cols = (size.width / pitch).ceil(), rows = (size.height / pitch).ceil();
    final base = dark ? const Color(0xFFD6C6D0) : const Color(0xFF3A4054);
    final dayTint = dark ? const Color(0xFFFFCE96) : const Color(0xFFE07A2A);
    final nightTint = dark ? const Color(0xFF7A8CE8) : const Color(0xFF2C3A80);
    const duskTint = Color(0xFFFF9646);
    final buckets = List.generate(6, (_) => <double>[]);
    for (var j = 0; j < rows; j++) {
      final y = (j + .5) * pitch;
      for (var i = 0; i < cols; i++) {
        final x = (i + .5) * pitch;
        final (lat, lon) = camera.toLatLon(Offset(x, y), size);
        if (lat > mapLatTop || lat < mapLatBottom || lon < -180 || lon > 180) continue;
        final f = landAtLatLon(lat, lon);
        if (f < .38) continue;
        final l = daylight(solarAltitude(lat, lon, sun));
        final light = l.dusk > .45 ? 1 : (l.night > .5 ? 2 : 0);
        buckets[light * 2 + (f < .62 ? 1 : 0)].addAll([x, y]);
      }
    }
    for (var k = 0; k < 6; k++) {
      if (buckets[k].isEmpty) continue;
      final light = k ~/ 2, rim = k.isOdd;
      final tint = [dayTint, duskTint, nightTint][light];
      final mix = [dark ? .22 : .18, .45, dark ? .58 : .5][light];
      canvas.drawRawPoints(ui.PointMode.points, Float32List.fromList(buckets[k]), Paint()
        ..strokeCap = StrokeCap.round
        ..strokeWidth = pitch * (rim ? .46 : .62)
        ..color = Color.lerp(base, tint, mix)!.withValues(alpha: rim ? .78 : .42));
    }
  }

  @override
  bool shouldRepaint(_LandPainter o) => o.camera != camera || o.c != c || o.sun != sun;
}

const mapLatTop = 83.0, mapLatBottom = -57.0;

class _PinsPainter extends CustomPainter {
  _PinsPainter({
    required this.camera,
    required this.servers,
    required this.clusters,
    required this.home,
    required this.selected,
    required this.hover,
    required this.connected,
    required this.c,
    required this.arc,
    required this.pulse,
  }) : super(repaint: Listenable.merge([arc, pulse]));
  final MapCamera camera;
  final List<MapServer> servers;
  final List<PinCluster> clusters;
  final (double, double)? home;
  final String? selected;
  final PinCluster? hover;
  final bool connected;
  final NbColors c;
  final Animation<double> arc, pulse;

  @override
  void paint(Canvas canvas, Size size) {
    final active = servers.where((s) => s.active || s.connecting).firstOrNull;
    final h = home;
    if (h != null) {
      final hp = camera.toScreen(h.$1, h.$2, size);
      if (active != null) {
        final ap = camera.toScreen(active.lat, active.lon, size);
        final mid = Offset((hp.dx + ap.dx) / 2, math.min(hp.dy, ap.dy) - (hp - ap).distance * .28);
        final path = Path()
          ..moveTo(hp.dx, hp.dy)
          ..quadraticBezierTo(mid.dx, mid.dy, ap.dx, ap.dy);
        final col = active.active ? c.sealed : c.amber;
        final metric = path.computeMetrics().firstOrNull;
        if (metric != null) {
          final t = Curves.easeOutCubic.transform(arc.value);
          final drawn = metric.extractPath(0, metric.length * t);
          canvas.drawPath(drawn, Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 6
            ..color = col.withValues(alpha: .12));
          canvas.drawPath(drawn, Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.8
            ..shader = ui.Gradient.linear(hp, ap, [col.withValues(alpha: .3), col]));
          // the flow: a short bright segment travelling to the server, while the tunnel is up or coming up
          if (t >= 1 && (pulse.isAnimating || active.connecting)) {
            final at = metric.length * (pulse.value % 1);
            canvas.drawPath(metric.extractPath(at, math.min(metric.length, at + 26)), Paint()
              ..style = PaintingStyle.stroke
              ..strokeWidth = 2.6
              ..strokeCap = StrokeCap.round
              ..color = col);
          }
        }
      }
      canvas.drawCircle(hp, 3.5, Paint()..color = c.text.withValues(alpha: .9));
      canvas.drawCircle(hp, 7, Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = c.text.withValues(alpha: .35));
    }
    for (final cl in clusters) {
      final lit = hover != null && hover!.names.join() == cl.names.join();
      if (!cl.single) {
        final r = 9.0 + math.min(6, cl.names.length.toDouble());
        canvas.drawCircle(cl.at, r, Paint()..color = c.surface.withValues(alpha: .92));
        canvas.drawCircle(cl.at, r, Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = lit ? 2 : 1.2
          ..color = lit ? c.orange : c.orangeA(.6));
        final tp = TextPainter(
          text: TextSpan(text: '${cl.names.length}', style: NbType.data(12, c.text)),
          textDirection: TextDirection.ltr,
        )..layout();
        tp.paint(canvas, cl.at - Offset(tp.width / 2, tp.height / 2));
        tp.dispose();
        continue;
      }
      final s = servers.firstWhere((x) => x.name == cl.names.single);
      final col = s.active
          ? c.sealed
          : s.connecting
          ? c.amber
          : switch (s.grade) {
              'fast' => c.sealed.withValues(alpha: .85),
              'fair' => c.amber.withValues(alpha: .85),
              'slow' => c.blocked.withValues(alpha: .85),
              _ => c.muted,
            };
      if (s.active && connected) {
        final k = pulse.isAnimating ? pulse.value * 2 % 1 : .3;
        canvas.drawCircle(cl.at, 6 + 14 * k, Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2 * (1 - k)
          ..color = col.withValues(alpha: .6 * (1 - k)));
      }
      if (s.active || s.connecting || lit) {
        canvas.drawCircle(cl.at, 14, Paint()
          ..shader = ui.Gradient.radial(cl.at, 14, [col.withValues(alpha: .40), col.withValues(alpha: 0)]));
      }
      final r = s.active ? 5.0 : (lit ? 4.6 : 3.6);
      canvas.drawCircle(cl.at, r, Paint()..color = col);
      canvas.drawCircle(cl.at, r, Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2
        ..color = c.bg.withValues(alpha: .85));
      if (s.name == selected) {
        canvas.drawCircle(cl.at, r + 5, Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.6
          ..color = c.orange);
      }
    }
  }

  @override
  bool shouldRepaint(_PinsPainter o) =>
      o.camera != camera || o.selected != selected || o.hover?.names.join() != hover?.names.join() ||
      o.connected != connected || o.c != c || o.home != home || o.servers != servers || o.clusters.length != clusters.length;
}
