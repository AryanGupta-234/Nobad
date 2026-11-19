/// An in-memory engine with the contract's shapes: tests, goldens and the explicit NOBAD_VPN_FAKE_ENGINE=1 demo.
/// The app never falls back to it: offline is shown as offline (main.dart).
library;

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import 'engine.dart';

class FakeEngine implements EngineApi {
  FakeEngine({
    Map<String, Object?>? state,
    this.connectDelay = const Duration(milliseconds: 1600),
    this.live = false,
    Link link = Link.connected,
  }) : _link = ValueNotifier(link) {
    _state = state ?? demoState();
    if (live) _tick = Timer.periodic(const Duration(seconds: 1), (_) => _traffic());
  }

  final Duration connectDelay;

  /// The demo: traffic every second while connected (tests leave it off: no timers).
  final bool live;
  final ValueNotifier<Link> _link;
  final _events = StreamController<EngineEvent>.broadcast();
  late Map<String, Object?> _state;
  Timer? _tick;
  final calls = <(String, Map<String, Object?>)>[];
  final _rng = math.Random(7);
  var _t = 0.0;

  Map<String, Object?> get rawState => _state;
  void setLink(Link l) => _link.value = l;

  @override
  ValueListenable<Link> get link => _link;
  @override
  Stream<EngineEvent> get events => _events.stream;
  @override
  String get engineVersion => '2.0.0-demo';
  @override
  Future<void> shown(bool on) async {}

  void emit(String name, Object? params) {
    if (!_events.isClosed) _events.add(EngineEvent(name, params));
  }

  void patch(Map<String, Object?> changes) {
    _state = {..._state, ...changes};
    emit('state', _state);
  }

  Map<String, Object?> get _settings => Map<String, Object?>.from(_state['settings'] as Map);

  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) async {
    if (_link.value != Link.connected) throw const EngineOffline();
    calls.add((method, params));
    switch (method) {
      case 'state':
        return _state;
      case 'connect':
        final name = params['name'];
        final names = [for (final r in _state['regions'] as List) (r as Map)['name']];
        if (!names.contains(name)) return {'ok': false, 'error': 'unknown server'};
        patch({'connecting': name, 'connected': false, 'error': null});
        Future<void>.delayed(connectDelay, () {
          final s = _settings..['last_region'] = name;
          patch({'connecting': null, 'connected': true, 'active': name, 'since': _now(), 'ks_active': s['kill_switch'] == true,
              'dns_active': true, 'settings': s, 'exit': {'ip': '203.0.113.7', 'city': 'Tokyo', 'country': 'JP'},
              'health': {'rtt': 61.0, 'loss': 0, 'jitter': 2.4, 'q': 'great'}});
        });
        return {'ok': true};
      case 'disconnect':
        patch({'connected': false, 'connecting': null, 'active': null, 'since': null, 'ks_active': false,
            'dns_active': false, 'health': null, 'exit': null});
        return {'ok': true};
      case 'fastest':
      case 'smart':
        final best = (_state['regions'] as List).cast<Map>().first['name'];
        return call('connect', {'name': best});
      case 'favorite':
        final s = _settings;
        final fav = List<Object?>.from((s['favorites'] as List?) ?? const []);
        fav.contains(params['name']) ? fav.remove(params['name']) : fav.add(params['name']);
        patch({'settings': s..['favorites'] = fav});
        return {'ok': true};
      case 'settings':
        patch({'settings': _settings..[params['key'] as String] = params['value']});
        return {'ok': true};
      case 'theme':
        patch({'settings': _settings..['theme'] = params['value']});
        return {'ok': true};
      case 'wizard_done':
        patch({'settings': _settings..['wizard_done'] = true});
        return {'ok': true};
      case 'dismiss_error':
        patch({'error': null});
        return {'ok': true};
      case 'panic_reset':
        patch({'ks_active': false, 'connected': false, 'connecting': null, 'active': null});
        return {'ok': true};
      case 'free_scan':
        return {'ok': true, 'folder': r'C:\Users\you\Downloads', 'files': _freeFiles};
      case 'free_import':
        final files = (params['files'] as List).cast<String>();
        for (final f in _freeFiles) {
          if (files.contains(f['file'])) f['already'] = true;
        }
        return {'ok': true, 'imported': [for (final f in files) f.replaceAll('.conf', '')], 'errors': <String>[]};
      case 'ui_show':
        return {'ok': true, 'shown': false, 'launched': false};
      case 'config_validate':
        return {'ok': true, 'valid': '${params['text']}'.contains('[Interface]'), 'errors': <String>[], 'warnings': <String>[]};
      default:
        return {'ok': true};
    }
  }

  final _freeFiles = [
    {'file': 'wg-JP-FREE-3.conf', 'name': 'JP-FREE-3', 'country': 'Japan', 'host': '146.70.205.2', 'port': '51820',
        'provider': 'Proton VPN', 'already': false},
    {'file': 'wg-NL-FREE-12.conf', 'name': 'NL-FREE-12', 'country': 'Netherlands', 'host': '190.2.132.9',
        'port': '51820', 'provider': 'Proton VPN', 'already': true},
  ];

  void _traffic() {
    if (_state['connected'] != true) return;
    _t += 1;
    final wave = (math.sin(_t / 3) + 1) / 2;
    final burst = _rng.nextDouble() < .12 ? 3.0 : 1.0;
    emit('traffic', {
      'rx_bps': (2.2e6 + 9e6 * wave * burst + _rng.nextDouble() * 8e5),
      'tx_bps': (2.4e5 + 6e5 * (1 - wave) + _rng.nextDouble() * 1e5),
    });
  }

  double _now() => DateTime.now().millisecondsSinceEpoch / 1000;

  @override
  void dispose() {
    _tick?.cancel();
    _events.close();
  }
}

Map<String, Object?> _region(String name, String host, String country, String city, double? rtt,
        {bool enc = false, bool v6 = false}) =>
    {
      'name': name,
      'host': host,
      'port': 51820,
      'ping': rtt == null ? null : {'rtt': rtt, 'loss': 0, 'jitter': 2.1},
      'geo': country.isEmpty ? null : {'country': country, 'city': city},
      'full': true,
      'v6': v6,
      'dns': true,
      'enc': enc,
    };

/// The demo PC: three free Proton servers and a home router, the kill switch on.
Map<String, Object?> demoState({bool connected = false, bool wizardDone = true, bool empty = false}) => {
  'connected': connected,
  'connecting': null,
  'note': null,
  'active': connected ? 'JP-FREE-3' : null,
  'since': connected ? DateTime(2026, 11, 19, 9, 12).millisecondsSinceEpoch / 1000 : null,
  'ks_active': connected,
  'dns_active': connected,
  'fw_off': false,
  'giveup': false,
  'settings': {
    'kill_switch': true,
    'dns_leak_block': true,
    'force_tunnel_dns': true,
    'fallback_dns': '1.1.1.1, 1.0.0.1',
    'ks_strict': false,
    'watchdog': true,
    'auto_repair': true,
    'stream_tuned': true,
    'reconnect_on_network_change': true,
    'smart_select': true,
    'tray': true,
    'close_to_tray': true,
    'notifications': true,
    'theme': 'dark',
    'wizard_done': wizardDone,
    'last_region': 'JP-FREE-3',
    'favorites': ['JP-FREE-3'],
    'trusted_networks': ['Home-WiFi'],
    'guard_service': '',
    'et_vpn_below': 'C',
    'et_enabled': true,
  },
  'regions': empty
      ? <Object?>[]
      : [
          _region('JP-FREE-3', 'jp-free-3.protonvpn.net', 'JP', 'Tokyo', 61, enc: true),
          _region('NL-FREE-12', 'nl-free-12.protonvpn.net', 'NL', 'Amsterdam', 148, v6: true),
          _region('US-FREE-34', 'us-free-34.protonvpn.net', 'US', 'New York', 212),
          _region('Home-Router', 'home.example.net', '', '', null), // the engine couldn't place it
        ],
  'admin': true,
  'wireguard': true,
  'wg_installing': false,
  'wg_cli': true,
  'exit': connected ? {'ip': '203.0.113.7', 'city': 'Tokyo', 'country': 'JP'} : null,
  'health': connected ? {'rtt': 61.0, 'loss': 0, 'jitter': 2.4, 'q': 'great'} : null,
  'home': {'country': 'IN'},
  'sessions': <Object?>[],
  'error': null,
  'log': [
    {'ts': '09:12:04', 'msg': 'connected to JP-FREE-3 (handshake 0.4 s)', 'level': 'ok'},
  ],
  'tray': true,
  'autostart': false,
  'update': {'current': '2.0.0', 'configured': false},
  'crash_pending': 0,
  'network': {'name': 'Home-WiFi', 'events': true, 'pending': null},
  'frozen': false,
  'eviltwin': null,
};
