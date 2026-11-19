/// The world map's maths, pure and tested (test/map/world_test.dart): where the sun is, how high it stands over
/// any point (day, twilight, night), which cells are land, where a point lands on the map, and where a server whose
/// address hasn't been located yet probably is (from its name). Ported from the WebView UI (nobadvpn/ui/app.js:
/// sunPos, nightMask, land, proj, guessPlace) so both draw the same world.
library;

import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'world_data.dart';

const _rad = math.pi / 180;

/// The point on Earth where the sun is straight overhead: (latitude, longitude) in degrees, longitude -180..180.
/// The low-precision solar formulas (good to about 0.01 degrees), from the UTC time.
(double, double) subsolarPoint(DateTime when) {
  final t = when.toUtc().millisecondsSinceEpoch / 864e5 - 10957.5; // days since J2000.0
  final g = (357.529 + .98560028 * t) * _rad;
  final q = 280.459 + .98564736 * t;
  final l = (q + 1.915 * math.sin(g) + .02 * math.sin(2 * g)) * _rad;
  final e = (23.439 - 3.6e-7 * t) * _rad;
  final dec = math.asin(math.sin(e) * math.sin(l));
  final ra = math.atan2(math.cos(e) * math.sin(l), math.cos(l)) / _rad;
  final gmst = (280.46061837 + 360.98564736629 * t) % 360;
  final lon = ((ra - gmst) % 360 + 540) % 360 - 180;
  return (dec / _rad, lon);
}

/// How high the sun stands over (lat, lon), in degrees: 90 overhead, 0 on the horizon, negative at night.
double solarAltitude(double lat, double lon, (double, double) sun) {
  final (sLat, sLon) = sun;
  final a = math.sin(lat * _rad) * math.sin(sLat * _rad) +
      math.cos(lat * _rad) * math.cos(sLat * _rad) * math.cos((lon - sLon) * _rad);
  return math.asin(a.clamp(-1.0, 1.0)) / _rad;
}

double smoothstep(double x) => x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x));

/// Light at a point from the sun's altitude: `night` 0..1 (fully night 10 degrees below the horizon) and `dusk`
/// 0..1 (the twilight band around -2 degrees), as the WebView map shades it.
({double night, double dusk}) daylight(double altitude) => (
  night: smoothstep(((2 - altitude) / 12).clamp(0.0, 1.0)),
  dusk: smoothstep(math.max(0, 1 - (altitude + 2).abs() / 4.5)),
);

/// The land mask, decoded once: 1 = land, row-major landCols x landRows.
final Uint8List landBits = () {
  final b = base64Decode(landBase64);
  final a = Uint8List(landCols * landRows);
  for (var i = 0; i < a.length; i++) {
    a[i] = (b[i >> 3] >> (7 - (i & 7))) & 1;
  }
  return a;
}();

/// A lightly blurred copy of the mask, so coasts sample smoothly.
final Float32List _field = () {
  final a = Float32List(landCols * landRows);
  for (var y = 0; y < landRows; y++) {
    for (var x = 0; x < landCols; x++) {
      var sum = 0.0, wt = 0.0;
      for (var dy = -1; dy <= 1; dy++) {
        for (var dx = -1; dx <= 1; dx++) {
          final yy = y + dy;
          if (yy < 0 || yy >= landRows) continue;
          final xx = (x + dx + landCols) % landCols;
          final w = (dx != 0 && dy != 0) ? 1.0 : ((dx != 0 || dy != 0) ? 2.0 : 10.0);
          sum += landBits[yy * landCols + xx] * w;
          wt += w;
        }
      }
      a[y * landCols + x] = sum / wt;
    }
  }
  return a;
}();

/// How much land is at mask position (u, v) in cells (bilinear over the blurred mask): 0 sea .. 1 land.
double landAt(double u, double v) {
  final x = u - .5, y = v - .5;
  final x0 = x.floor(), y0 = y.floor();
  final fx = x - x0, fy = y - y0;
  double g(int xx, int yy) => (yy < 0 || yy >= landRows) ? 0 : _field[yy * landCols + ((xx % landCols) + landCols) % landCols];
  return (g(x0, y0) * (1 - fx) + g(x0 + 1, y0) * fx) * (1 - fy) + (g(x0, y0 + 1) * (1 - fx) + g(x0 + 1, y0 + 1) * fx) * fy;
}

/// Land at a latitude and longitude (0..1).
double landAtLatLon(double lat, double lon) =>
    landAt((lon + 180) / 360 * landCols, (mapLat0 - lat) / mapLatSpan * landRows);

/// Where (lat, lon) is on a map of [w] x [h]: x from -180..180, y from mapLat0 down mapLatSpan degrees.
(double, double) project(double lat, double lon, double w, double h) =>
    ((lon + 180) / 360 * w, (mapLat0 - lat) / mapLatSpan * h);

Map<String, (double, double)> _coords(String t) => {
  for (final e in t.split(','))
    if (e.split(' ').length == 3) e.split(' ')[0]: (double.parse(e.split(' ')[1]), double.parse(e.split(' ')[2])),
};
Map<String, String> _alias(String t) => {
  for (final e in t.split(','))
    if (e.contains('=')) e.split('=')[0]: e.split('=')[1],
};

final _city = _coords(cityTable);
final _country = _coords(countryTable);
final _air = _alias(airportTable);
final _iso = _alias(isoTable);
final _cityKeys = _city.keys.where((k) => k.length > 5).toList()..sort((a, b) => b.length - a.length);
final _countryKeys = _country.keys.where((k) => k.length > 5).toList()..sort((a, b) => b.length - a.length);
final _wordCodes = RegExp(r'^(is|it|no|be|am|at|my|me|id|co|ma|pe|ar|in)$');

/// Where a server probably is, from its name ("Frankfurt", "NewYork", "us-nyc-01", "de-fra", "Tokyo 2", "SG"),
/// for servers whose endpoint hasn't been located yet. Null when the name says nothing.
(double, double)? guessPlace(String name) {
  final split = name.replaceAllMapped(RegExp(r'([a-z])([A-Z])'), (m) => '${m[1]} ${m[2]}').toLowerCase();
  final toks = split.split(RegExp(r'[^a-z]+')).where((t) => t.isNotEmpty).toList();
  final joined = toks.join();
  for (final k in _cityKeys) {
    if (joined.contains(k)) return _city[k];
  }
  for (final t in toks) {
    if (_city.containsKey(t)) return _city[t];
  }
  for (final t in toks) {
    if (_air.containsKey(t)) return _city[_air[t]];
  }
  for (final k in _countryKeys) {
    if (joined.contains(k)) return _country[k];
  }
  for (final t in toks) {
    if (_country.containsKey(t)) return _country[t];
  }
  if (toks.isNotEmpty) {
    final c2 = toks.first;
    if (c2.length == 2 && _iso.containsKey(c2) && (toks.length == 1 || !_wordCodes.hasMatch(c2))) {
      return _country[_iso[c2]];
    }
  }
  return null;
}

/// A country's usual point from its ISO code ("JP" -> Tokyo's), for a server the engine located only to a country.
(double, double)? countryPoint(String iso2) {
  final n = _iso[iso2.toLowerCase()];
  return n == null ? null : _country[n];
}
