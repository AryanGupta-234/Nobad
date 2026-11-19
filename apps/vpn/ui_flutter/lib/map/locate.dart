/// Where a server goes on the map, from what is known, best first: the engine's located endpoint (offline country
/// database, or the online lookup when the user switched it on), a place in the server's name ("de-fra",
/// "Tokyo 2"), or its country's usual point. Null: the window says "location unknown" instead of a wrong pin.
library;

import '../engine/models.dart';
import 'map_view.dart';
import 'world.dart';

(double, double)? locate(Region r) {
  if (r.lat != null && r.lon != null) return (r.lat!, r.lon!);
  return guessPlace(r.name) ?? (r.country.isEmpty ? null : countryPoint(r.country));
}

/// The servers that can be placed, as map pins.
List<MapServer> mapServers(VpnState s) => [
  for (final r in s.regions)
    if (locate(r) case final at?)
      MapServer(
        name: r.name,
        lat: at.$1,
        lon: at.$2,
        place: r.place,
        endpoint: r.endpoint,
        rtt: r.ping?.rtt,
        grade: r.ping?.grade ?? 'none',
        active: s.connected && s.active == r.name,
        connecting: s.connecting == r.name,
      ),
];

/// The chip on the map: "Connected · Tokyo, JP · 61 ms", "Connecting to NL-FREE-12…", or how many are placed.
String mapStatus(VpnState s) {
  final placed = mapServers(s).length, unknown = s.regions.length - placed;
  if (s.connected && s.active != null) {
    final r = s.region(s.active);
    final where = r == null || r.place.isEmpty ? s.active! : r.place;
    final rtt = s.health?.rtt;
    return ['Connected', where, if (rtt != null) '${rtt.round()} ms'].join(' · ');
  }
  if (s.connecting != null) return 'Connecting to ${s.connecting}…';
  if (s.regions.isEmpty) return 'No servers yet';
  return '$placed on the map${unknown > 0 ? ' · $unknown location unknown' : ''}';
}
