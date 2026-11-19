/// The interactive map's maths, pure and tested (test/map/camera_test.dart): the camera (where the map is centred
/// and how far it is zoomed), projecting between latitude/longitude and the view, zooming about the cursor, panning
/// within limits, fitting a set of points, clustering pins that sit close together on screen, and hit-testing.
///
/// The projection is the WebView map's (equirectangular, latitude 83 down to -57, aspect 160:62 widened by 1.24),
/// so a world view at zoom 1 is exactly the old map.
library;

import 'dart:math' as math;
import 'dart:ui';

import 'world_data.dart';

/// Map height over width at zoom 1.
const mapAspectInverse = landRows * 1.24 / landCols;
const _latTop = mapLat0, _latBottom = mapLat0 - mapLatSpan;

class MapCamera {
  const MapCamera({required this.lat, required this.lon, required this.zoom});

  /// The centre of the view.
  final double lat, lon;

  /// 1 = the whole world across the view's width.
  final double zoom;

  static const minZoom = 1.0, maxZoom = 8.0, focusZoom = 2.4;

  /// Fitting never zooms in further than this: the land mask is coarse, and context matters more than detail.
  static const fitZoom = 1.8;
  static const world = MapCamera(lat: _latTop - mapLatSpan / 2, lon: 0, zoom: 1);

  /// World units: x 0..1 across longitude, y 0..aspect down latitude.
  static Offset _world(double lat, double lon) =>
      Offset((lon + 180) / 360, (_latTop - lat) / mapLatSpan * mapAspectInverse);

  static (double, double) _unworld(Offset w) =>
      (_latTop - w.dy / mapAspectInverse * mapLatSpan, w.dx * 360 - 180);

  /// Pixels per world unit: the width of the world at this zoom.
  double _scale(Size view) => view.width * zoom;

  Offset toScreen(double lat, double lon, Size view) {
    final s = _scale(view);
    return (_world(lat, lon) - _world(this.lat, this.lon)) * s + view.center(Offset.zero);
  }

  (double, double) toLatLon(Offset p, Size view) {
    final s = _scale(view);
    return _unworld((p - view.center(Offset.zero)) / s + _world(lat, lon));
  }

  /// Keeps the centre where the map still fills as much of the view as it can.
  MapCamera clamped(Size view) {
    final z = zoom.clamp(minZoom, maxZoom);
    final halfW = .5 / z, halfH = view.height / view.width / z / 2;
    final w = _world(lat, lon);
    final x = halfW >= .5 ? .5 : w.dx.clamp(halfW, 1 - halfW);
    final maxY = mapAspectInverse;
    final y = halfH * 2 >= maxY ? maxY / 2 : w.dy.clamp(halfH, maxY - halfH);
    final (la, lo) = _unworld(Offset(x, y));
    return MapCamera(lat: la.clamp(_latBottom, _latTop), lon: lo.clamp(-180, 180), zoom: z);
  }

  /// Zoom to [newZoom] keeping the point under [at] where it is.
  MapCamera zoomAbout(Offset at, double newZoom, Size view) {
    final z = newZoom.clamp(minZoom, maxZoom);
    final (la, lo) = toLatLon(at, view);
    final probe = MapCamera(lat: lat, lon: lon, zoom: z);
    final drift = probe.toScreen(la, lo, view) - at;
    final (cla, clo) = probe.toLatLon(view.center(Offset.zero) + drift, view);
    final out = MapCamera(lat: cla, lon: clo, zoom: z);
    return z == zoom && z == minZoom ? this : out.clamped(view);
  }

  /// Drag by [delta] pixels.
  MapCamera pan(Offset delta, Size view) {
    final (la, lo) = toLatLon(view.center(Offset.zero) - delta, view);
    return MapCamera(lat: la, lon: lo, zoom: zoom).clamped(view);
  }

  /// The camera that shows every point with a margin, or the world for none; one point: [focusZoom] on it.
  static MapCamera fit(List<(double, double)> points, Size view, {double margin = 40}) {
    if (points.isEmpty || view.isEmpty) return world;
    if (points.length == 1) {
      return MapCamera(lat: points.first.$1, lon: points.first.$2, zoom: focusZoom).clamped(view);
    }
    final ws = [for (final (la, lo) in points) _world(la, lo)];
    final minX = ws.map((w) => w.dx).reduce(math.min), maxX = ws.map((w) => w.dx).reduce(math.max);
    final minY = ws.map((w) => w.dy).reduce(math.min), maxY = ws.map((w) => w.dy).reduce(math.max);
    final innerW = math.max(1.0, view.width - 2 * margin), innerH = math.max(1.0, view.height - 2 * margin);
    final zx = innerW / view.width / math.max(1e-6, maxX - minX);
    final zy = innerH / view.width / math.max(1e-6, maxY - minY);
    final z = math.min(zx, zy).clamp(minZoom, fitZoom);
    final (la, lo) = _unworld(Offset((minX + maxX) / 2, (minY + maxY) / 2));
    return MapCamera(lat: la, lon: lo, zoom: z).clamped(view);
  }

  static MapCamera lerp(MapCamera a, MapCamera b, double t) {
    if (t >= 1) return b;
    double l(double x, double y) => x + (y - x) * t;
    return MapCamera(lat: l(a.lat, b.lat), lon: l(a.lon, b.lon), zoom: l(a.zoom, b.zoom));
  }

  @override
  bool operator ==(Object other) => other is MapCamera && other.lat == lat && other.lon == lon && other.zoom == zoom;

  @override
  int get hashCode => Object.hash(lat, lon, zoom);

  @override
  String toString() => 'MapCamera($lat, $lon, x$zoom)';
}

/// A pin where it is on screen. [keep]: never merged into a cluster (the active server).
class ScreenPin {
  const ScreenPin(this.name, this.at, {this.keep = false});
  final String name;
  final Offset at;
  final bool keep;
}

class PinCluster {
  const PinCluster(this.names, this.at);
  final List<String> names;
  final Offset at;
  bool get single => names.length == 1;
}

/// Greedy clustering: each pin joins the first cluster whose centre is within [radius] pixels, else starts one.
/// Pins marked keep always stand alone.
List<PinCluster> cluster(List<ScreenPin> pins, {double radius = 18}) {
  final groups = <(List<ScreenPin>, bool)>[];
  for (final p in pins) {
    if (p.keep) {
      groups.add(([p], true));
      continue;
    }
    var placed = false;
    for (final (g, locked) in groups) {
      if (locked) continue;
      final c = g.fold(Offset.zero, (s, x) => s + x.at) / g.length.toDouble();
      if ((c - p.at).distance <= radius) {
        g.add(p);
        placed = true;
        break;
      }
    }
    if (!placed) groups.add(([p], false));
  }
  return [
    for (final (g, _) in groups) PinCluster([for (final p in g) p.name], g.fold(Offset.zero, (s, x) => s + x.at) / g.length.toDouble()),
  ];
}

/// The cluster nearest [p] within [reach] pixels, or null.
PinCluster? hitTest(List<PinCluster> clusters, Offset p, {double reach = 12}) {
  PinCluster? best;
  var bestD = double.infinity;
  for (final c in clusters) {
    final d = (c.at - p).distance;
    final r = reach + (c.single ? 0 : 6);
    if (d <= r && d < bestD) {
      best = c;
      bestD = d;
    }
  }
  return best;
}
