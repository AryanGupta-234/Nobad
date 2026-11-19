import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_vpn_ui/map/world.dart';

void main() {
  group('the sun', () {
    test('stands over the equator at the March equinox and over the tropic in June', () {
      final (latMar, _) = subsolarPoint(DateTime.utc(2026, 3, 20, 14, 46));
      expect(latMar.abs(), lessThan(.1));
      final (latJun, _) = subsolarPoint(DateTime.utc(2026, 6, 21, 8, 24));
      expect(latJun, closeTo(23.44, .05));
      final (latDec, _) = subsolarPoint(DateTime.utc(2026, 12, 21, 20, 50));
      expect(latDec, closeTo(-23.44, .05));
    });

    test('is near the Greenwich meridian at 12:00 UTC (within the equation of time)', () {
      for (final m in [1, 4, 7, 10]) {
        final (_, lon) = subsolarPoint(DateTime.utc(2026, m, 15, 12));
        expect(lon.abs(), lessThan(5), reason: 'month $m');
      }
      final (_, lon18) = subsolarPoint(DateTime.utc(2026, 4, 15, 18));
      expect(lon18, closeTo(-90, 5));
    });

    test('altitude: overhead at the subsolar point, below the horizon on the far side', () {
      final sun = subsolarPoint(DateTime.utc(2026, 11, 19, 9));
      final (lat, lon) = sun;
      expect(solarAltitude(lat, lon, sun), closeTo(90, 1e-6));
      expect(solarAltitude(-lat, lon + 180, sun), closeTo(-90, 1e-6));
      expect(solarAltitude(0, lon + 90, sun), closeTo(0, 1e-6)); // a quarter turn away on the equator: sunrise or sunset
    });

    test('daylight: night, twilight and day bands', () {
      expect(daylight(40).night, 0);
      expect(daylight(-20).night, 1);
      expect(daylight(-2).dusk, 1);
      expect(daylight(30).dusk, 0);
      final mid = daylight(-4);
      expect(mid.night, inExclusiveRange(0, 1));
    });
  });

  group('the land', () {
    test('cities are on land, oceans are not', () {
      expect(landAtLatLon(48.86, 2.35), greaterThan(.6)); // Paris
      expect(landAtLatLon(39, -98), greaterThan(.6)); // the middle of the US
      expect(landAtLatLon(-25, 135), greaterThan(.6)); // Australia
      expect(landAtLatLon(30, -40), lessThan(.2)); // the Atlantic
      expect(landAtLatLon(0, -150), lessThan(.2)); // the Pacific
    });

    test('projection puts the corners where the mask starts and ends', () {
      expect(project(83, -180, 1600, 620), (0.0, 0.0));
      expect(project(-57, 180, 1600, 620), (1600.0, 620.0));
    });
  });

  group('guessing a place from a server name', () {
    test('cities, airports, countries and ISO codes', () {
      expect(guessPlace('Frankfurt-2'), (50.11, 8.68));
      expect(guessPlace('NewYork'), (40.71, -74.01));
      expect(guessPlace('us-nyc-01'), (40.71, -74.01));
      expect(guessPlace('de-fra'), (50.11, 8.68));
      expect(guessPlace('Tokyo 2'), (35.68, 139.69));
      expect(guessPlace('SG'), (1.35, 103.8));
      expect(guessPlace('JP-FREE-3'), (35.7, 139.7));
      expect(guessPlace('Home-Router'), isNull);
      expect(guessPlace('in-house'), isNull); // "in" is a word, not India, unless alone
    });

    test('a country code alone', () {
      expect(countryPoint('NL'), (52.4, 4.9));
      expect(countryPoint('ZZ'), isNull);
    });
  });
}
