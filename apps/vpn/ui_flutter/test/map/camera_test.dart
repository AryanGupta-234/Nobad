import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_vpn_ui/map/camera.dart';

void main() {
  const view = Size(800, 400);

  group('camera', () {
    test('zoom 1 shows the whole map; projection and its inverse agree', () {
      const cam = MapCamera.world;
      final p = cam.toScreen(48.86, 2.35, view);
      final (lat, lon) = cam.toLatLon(p, view);
      expect(lat, closeTo(48.86, 1e-9));
      expect(lon, closeTo(2.35, 1e-9));
      final tl = cam.toScreen(83, -180, view), br = cam.toScreen(-57, 180, view);
      expect(tl.dx, closeTo(0, 1e-9));
      expect(br.dx, closeTo(800, 1e-9));
      expect((br.dy - tl.dy) / (br.dx - tl.dx), closeTo(mapAspectInverse, 1e-9));
    });

    test('zooming about a point keeps that point under the cursor', () {
      const cam = MapCamera.world;
      const at = Offset(600, 150);
      final before = cam.toLatLon(at, view);
      final z = cam.zoomAbout(at, 2.5, view);
      final after = z.toLatLon(at, view);
      expect(after.$1, closeTo(before.$1, 1e-6));
      expect(after.$2, closeTo(before.$2, 1e-6));
      expect(z.zoom, 2.5);
    });

    test('zoom and pan stay within limits', () {
      final z = MapCamera.world.zoomAbout(const Offset(400, 200), 100, view);
      expect(z.zoom, MapCamera.maxZoom);
      final out = MapCamera.world.zoomAbout(const Offset(400, 200), .1, view);
      expect(out.zoom, MapCamera.minZoom);
      final far = MapCamera.world.pan(const Offset(-99999, 99999), view);
      expect(far.lon, inInclusiveRange(-180, 180));
      expect(far.lat, inInclusiveRange(-57, 83));
    });

    test('fit puts every point inside the view, centred, with a margin', () {
      final pts = [(50.11, 8.68), (35.68, 139.69), (40.71, -74.01)];
      final cam = MapCamera.fit(pts, view);
      for (final (la, lo) in pts) {
        final p = cam.toScreen(la, lo, view);
        expect(p.dx, inInclusiveRange(20, 780));
        expect(p.dy, inInclusiveRange(20, 380));
      }
      final one = MapCamera.fit([(50.11, 8.68)], view);
      expect(one.zoom, MapCamera.focusZoom);
      expect(one.toScreen(50.11, 8.68, view), offsetMoreOrLess(const Offset(400, 200)));
      expect(MapCamera.fit([], view), MapCamera.world);
    });

    test('lerp eases between two cameras', () {
      final a = MapCamera.world, b = MapCamera(lat: 50, lon: 8, zoom: 4);
      final m = MapCamera.lerp(a, b, .5);
      expect(m.zoom, closeTo(2.5, 1e-9));
      expect(MapCamera.lerp(a, b, 1), b);
    });
  });

  group('clusters and hits', () {
    test('pins closer than the radius on screen join; far ones stay apart', () {
      final cs = cluster([
        const ScreenPin('a', Offset(100, 100)),
        const ScreenPin('b', Offset(108, 104)),
        const ScreenPin('c', Offset(300, 100)),
      ], radius: 18);
      expect(cs.length, 2);
      final big = cs.firstWhere((c) => c.names.length == 2);
      expect(big.names, ['a', 'b']);
      expect(big.at, offsetMoreOrLess(const Offset(104, 102)));
    });

    test('a hit is the nearest cluster within reach, or nothing', () {
      final cs = cluster([const ScreenPin('a', Offset(100, 100)), const ScreenPin('c', Offset(300, 100))], radius: 18);
      expect(hitTest(cs, const Offset(104, 97), reach: 12)?.names, ['a']);
      expect(hitTest(cs, const Offset(200, 100), reach: 12), isNull);
    });

    test('the active pin is never hidden in a cluster', () {
      final cs = cluster([
        const ScreenPin('a', Offset(100, 100)),
        const ScreenPin('b', Offset(105, 100), keep: true),
      ], radius: 18);
      expect(cs.length, 2);
    });
  });
}

Matcher offsetMoreOrLess(Offset o) => predicate<Offset>((v) => (v - o).distance < .01, 'about $o');
