/// What the engine sends, as plain Dart: the state snapshot (contract/events.schema.json `State`), servers, traffic,
/// errors with actions, and the free-server guide's files. Every reader is forgiving: a missing or odd value becomes
/// a safe default, never an exception (an older or newer engine may add or drop keys).
library;

Map<String, Object?> jMap(Object? v) => v is Map ? Map<String, Object?>.from(v) : const {};
List<Object?> jList(Object? v) => v is List ? v : const [];
String jStr(Object? v, [String d = '']) => v is String ? v : d;
String? jStrN(Object? v) => v is String && v.isNotEmpty ? v : null;
bool jBool(Object? v) => v == true;
double? jNum(Object? v) => v is num ? v.toDouble() : null;
int jInt(Object? v, [int d = 0]) => v is int ? v : (v is num ? v.toInt() : d);

/// The four protection states the whole UI is built around (the tray uses the same four).
enum Protection {
  /// The tunnel is up and verified.
  protected,

  /// Connecting to a server.
  connecting,

  /// Not connected, and the kill switch blocks traffic outside the tunnel.
  blocked,

  /// Not connected, internet as normal.
  off,
}

class Ping {
  const Ping({this.rtt, this.loss, this.jitter, this.estimate = false});
  final double? rtt;
  final double? loss;
  final double? jitter;
  final bool estimate;

  static Ping? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return Ping(rtt: jNum(m['rtt']), loss: jNum(m['loss']), jitter: jNum(m['jitter']), estimate: jBool(m['est']));
  }

  /// Fast (< 80 ms), fair (< 180 ms), slow, or not answering: the legend of the old map.
  String get grade => rtt == null ? 'none' : (rtt! < 80 ? 'fast' : (rtt! < 180 ? 'fair' : 'slow'));
}

class Region {
  const Region({
    required this.name,
    required this.host,
    this.port,
    this.ping,
    this.country = '',
    this.city = '',
    this.full = false,
    this.v6 = false,
    this.dns = false,
    this.encrypted = false,
    this.lat,
    this.lon,
  });
  final String name;
  final String host;
  final int? port;
  final Ping? ping;
  final String country;
  final String city;
  final bool full;
  final bool v6;
  final bool dns;
  final bool encrypted;

  /// Where the engine located the endpoint (geo lookup), or null.
  final double? lat, lon;

  static Region fromJson(Object? v) {
    final m = jMap(v);
    final geo = jMap(m['geo']);
    final p = m['port'];
    return Region(
      name: jStr(m['name']),
      host: jStr(m['host']),
      port: p is int ? p : int.tryParse('${p ?? ''}'),
      ping: Ping.fromJson(m['ping']),
      country: jStr(geo['country']).toUpperCase(),
      city: jStr(geo['city']),
      full: jBool(m['full']),
      v6: jBool(m['v6']),
      dns: jBool(m['dns']),
      encrypted: jBool(m['enc']),
      lat: jNum(geo['lat']),
      lon: jNum(geo['lon']),
    );
  }

  Region withPing(Ping? p) => Region(
    name: name,
    host: host,
    port: port,
    ping: p,
    country: country,
    city: city,
    full: full,
    v6: v6,
    dns: dns,
    encrypted: encrypted,
    lat: lat,
    lon: lon,
  );

  String get endpoint => port == null ? host : '$host:$port';
  String get place => [city, country].where((s) => s.isNotEmpty).join(', ');
}

class ErrorAction {
  const ErrorAction(this.id, this.label);
  final String id;
  final String label;
}

/// A failed connect or a setup problem, with the actions the engine offers (Retry, Restore internet, ...).
class EngineError {
  const EngineError({required this.code, required this.title, this.detail = '', this.name, this.ts = 0, this.actions = const []});
  final String code;
  final String title;
  final String detail;
  final String? name;
  final int ts;
  final List<ErrorAction> actions;

  static EngineError? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return EngineError(
      code: jStr(m['code']),
      title: jStr(m['title'], "Something went wrong"),
      detail: jStr(m['detail']),
      name: jStrN(m['name']),
      ts: jInt(m['ts']),
      actions: [
        for (final a in jList(m['actions']))
          if (a is Map && a['id'] is String) ErrorAction(a['id'] as String, jStr(a['label'], a['id'] as String)),
      ],
    );
  }

  /// A failed attempt is news, not a state: these close by themselves (app_ext.js ERR_TRANSIENT).
  bool get transient => const {'handshake', 'start_failed', 'dns_endpoint', 'reconnect_failed'}.contains(code);
}

class LogEntry {
  const LogEntry(this.ts, this.msg, this.level);
  final String ts;
  final String msg;
  final String level;
  static LogEntry fromJson(Object? v) {
    final m = jMap(v);
    return LogEntry(jStr(m['ts']), jStr(m['msg']), jStr(m['level'], 'info'));
  }
}

class Health {
  const Health({this.rtt, this.loss, this.jitter, this.quality = ''});
  final double? rtt;
  final double? loss;
  final double? jitter;
  final String quality;
  static Health? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return Health(rtt: jNum(m['rtt']), loss: jNum(m['loss']), jitter: jNum(m['jitter']), quality: jStr(m['q']));
  }
}

class Update {
  const Update({this.current = '', this.version = '', this.available = false, this.busy = false, this.progress = 0,
      this.error = '', this.notes = '', this.configured = false, this.checked = false});
  final String current, version, error, notes;
  final bool available, busy, configured, checked;
  final int progress;
  static Update? fromJson(Object? v) {
    if (v is! Map) return null;
    final m = jMap(v);
    return Update(
      current: jStr(m['current']),
      version: jStr(m['version']),
      available: jBool(m['available']),
      busy: jBool(m['busy']),
      progress: jInt(m['progress']),
      error: jStr(m['error']),
      notes: jStr(m['notes']),
      configured: jBool(m['configured']),
      checked: jBool(m['checked']),
    );
  }
}

class VpnState {
  const VpnState({
    this.connected = false,
    this.connecting,
    this.note,
    this.active,
    this.since,
    this.ksActive = false,
    this.dnsActive = false,
    this.fwOff = false,
    this.giveup = false,
    this.settings = const {},
    this.regions = const [],
    this.admin = true,
    this.wireguard = true,
    this.wgInstalling = false,
    this.exitInfo = const {},
    this.health,
    this.error,
    this.log = const [],
    this.tray = false,
    this.autostart = false,
    this.update,
    this.crashPending = 0,
    this.networkName,
    this.pendingNetwork = const {},
    this.home = const {},
  });

  final bool connected;
  final String? connecting;
  final String? note;
  final String? active;
  final double? since;
  final bool ksActive, dnsActive, fwOff, giveup;
  final Map<String, Object?> settings;
  final List<Region> regions;
  final bool admin, wireguard, wgInstalling;
  final Map<String, Object?> exitInfo;
  final Health? health;
  final EngineError? error;
  final List<LogEntry> log;
  final bool tray, autostart;
  final Update? update;
  final int crashPending;
  final String? networkName;
  final Map<String, Object?> pendingNetwork;

  /// Where this PC is ({lat, lon, country}, from the exit-IP lookup while not connected), or empty.
  final Map<String, Object?> home;

  static VpnState fromJson(Object? v) {
    final m = jMap(v);
    final net = jMap(m['network']);
    return VpnState(
      connected: jBool(m['connected']),
      connecting: jStrN(m['connecting']),
      note: jStrN(m['note']),
      active: jStrN(m['active']),
      since: jNum(m['since']),
      ksActive: jBool(m['ks_active']),
      dnsActive: jBool(m['dns_active']),
      fwOff: jBool(m['fw_off']),
      giveup: jBool(m['giveup']),
      settings: jMap(m['settings']),
      regions: [for (final r in jList(m['regions'])) Region.fromJson(r)],
      admin: m['admin'] != false,
      wireguard: m['wireguard'] != false,
      wgInstalling: jBool(m['wg_installing']),
      exitInfo: jMap(m['exit']),
      health: Health.fromJson(m['health']),
      error: EngineError.fromJson(m['error']),
      log: [for (final e in jList(m['log'])) LogEntry.fromJson(e)],
      tray: jBool(m['tray']),
      autostart: jBool(m['autostart']),
      update: Update.fromJson(m['update']),
      crashPending: jInt(m['crash_pending']),
      networkName: jStrN(net['name']),
      pendingNetwork: jMap(net['pending']),
      home: jMap(m['home']),
    );
  }

  Protection get protection => connected
      ? Protection.protected
      : connecting != null
      ? Protection.connecting
      : ksActive
      ? Protection.blocked
      : Protection.off;

  bool setting(String k) => settings[k] == true;
  String settingText(String k) => jStr(settings[k]);
  List<String> get favorites => [for (final f in jList(settings['favorites'])) if (f is String) f];
  List<String> get trustedNetworks => [for (final f in jList(settings['trusted_networks'])) if (f is String) f];
  Map<String, Object?> get trustedFingerprints => jMap(settings['trusted_fingerprints']);
  String? get lastRegion => jStrN(settings['last_region']);
  bool get dark => settings['theme'] != 'light';
  bool get wizardDone => settings['wizard_done'] == true;

  /// The server the connect button means right now: the active or connecting one, else the last, else the first.
  String? get target {
    if (active != null && connected) return active;
    if (connecting != null) return connecting;
    final names = regions.map((r) => r.name).toSet();
    if (lastRegion != null && names.contains(lastRegion)) return lastRegion;
    return regions.isEmpty ? null : regions.first.name;
  }

  Region? region(String? name) {
    for (final r in regions) {
      if (r.name == name) return r;
    }
    return null;
  }

  String? get exitIp => jStrN(exitInfo['ip']);
  String get exitPlace => [jStr(exitInfo['city']), jStr(exitInfo['country'])].where((s) => s.isNotEmpty).join(', ');
  bool get exitLookupOff => jBool(exitInfo['disabled']);
}

class Traffic {
  const Traffic(this.rxBps, this.txBps, {this.rxTotal = 0, this.txTotal = 0});
  final double rxBps, txBps;
  final int rxTotal, txTotal;
  static Traffic fromJson(Object? v) {
    final m = jMap(v);
    return Traffic(jNum(m['rx_bps']) ?? 0, jNum(m['tx_bps']) ?? 0,
        rxTotal: jInt(m['rx_total']), txTotal: jInt(m['tx_total']));
  }
}

/// One WireGuard file the free-server guide found in Downloads (configstore.downloads_scan).
class FreeFile {
  const FreeFile({required this.file, this.name = '', this.country = '', this.host = '', this.port = '',
      this.provider = '', this.already = false});
  final String file, name, country, host, port, provider;
  final bool already;
  static FreeFile fromJson(Object? v) {
    final m = jMap(v);
    return FreeFile(
      file: jStr(m['file']),
      name: jStr(m['name']),
      country: jStr(m['country']),
      host: jStr(m['host']),
      port: m['port'] == null ? '' : '${m['port']}',
      provider: jStr(m['provider']),
      already: jBool(m['already']),
    );
  }
}

/// An action's answer: `{ok, error, ...}` (rpc/methods.py shape()).
class Answer {
  const Answer(this.ok, this.error, this.data);
  final bool ok;
  final String error;
  final Map<String, Object?> data;
  static Answer fromJson(Object? v) {
    final m = jMap(v);
    return Answer(jBool(m['ok']), jStr(m['error']), m);
  }
}

// ---------------------------------------------------------------- formatting
/// Bits per second as the old mini window wrote them (mini.js rate()).
String rate(double bps) => bps >= 1e6
    ? '${(bps / 1e6).toStringAsFixed(1)} Mbps'
    : bps >= 1e3
    ? '${(bps / 1e3).round()} kbps'
    : '${bps.round()} bps';

String bytes(num b) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var v = b.toDouble();
  var i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return i == 0 ? '${v.round()} B' : '${v.toStringAsFixed(v < 10 ? 1 : 0)} ${units[i]}';
}

String ms(double? v) => v == null ? '—' : '${v.round()} ms';

String uptime(double? since, DateTime now) {
  if (since == null) return '—';
  final s = now.millisecondsSinceEpoch / 1000 - since;
  if (s < 0) return '0s';
  final d = Duration(seconds: s.round());
  if (d.inHours > 0) return '${d.inHours}h ${d.inMinutes % 60}m';
  if (d.inMinutes > 0) return '${d.inMinutes}m ${d.inSeconds % 60}s';
  return '${d.inSeconds}s';
}
