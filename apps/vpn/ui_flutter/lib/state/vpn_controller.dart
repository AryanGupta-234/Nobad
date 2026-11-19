/// The window's one source of truth: the engine's state snapshot, the live traffic and latency samples, which
/// long tasks are running, and the toasts. Fed only by engine events (no polling timers).
library;

import 'dart:async';
import 'dart:collection';

import 'package:flutter/foundation.dart';

import '../engine/engine.dart';
import '../engine/models.dart';

class Toast {
  Toast(this.text, {this.good = false}) : id = _next++;
  static var _next = 0;
  final int id;
  final String text;
  final bool good;
}

/// A fixed window of throughput samples (bits per second), newest last.
class Samples {
  Samples(this.capacity);
  final int capacity;
  final rx = ListQueue<double>();
  final tx = ListQueue<double>();

  /// Bumped on every sample: the chart repaints only when this changes.
  final revision = ValueNotifier(0);

  void add(double r, double t) {
    rx.addLast(r);
    tx.addLast(t);
    while (rx.length > capacity) {
      rx.removeFirst();
      tx.removeFirst();
    }
    revision.value++;
  }

  void clear() {
    rx.clear();
    tx.clear();
    revision.value++;
  }

  double get peak {
    var m = 0.0;
    for (final v in rx) {
      if (v > m) m = v;
    }
    for (final v in tx) {
      if (v > m) m = v;
    }
    return m;
  }
}

class VpnController extends ChangeNotifier {
  VpnController(this.engine, {this.onShow, this.onQuitting}) {
    _sub = engine.events.listen(_event);
    engine.link.addListener(_linked);
    _linked();
  }

  final EngineApi engine;

  /// The engine asked for a window ("main" / "mini").
  final void Function(String window)? onShow;

  /// The engine is quitting (Quit from the tray or Settings): the window closes too.
  final VoidCallback? onQuitting;
  late final StreamSubscription<EngineEvent> _sub;

  VpnState? state;
  Traffic traffic = const Traffic(0, 0);
  final samples = Samples(90);
  final toasts = <Toast>[];
  final busy = <String>{};
  final logLines = <LogEntry>[];

  /// The newest endpoint report, network repair result and update state, for the screens that show them.
  Map<String, Object?> endpointReport = const {};
  Map<String, Object?> lastRepair = const {};

  /// The server picked in the list or on the map (null: none). The aperture connects to it.
  String? selected;

  void select(String? name) {
    if (name == selected) return;
    selected = name;
    notifyListeners();
  }

  Link get link => engine.link.value;
  bool get online => link == Link.connected && state != null;

  void _linked() {
    if (engine.link.value == Link.connected) {
      unawaited(refresh());
    }
    notifyListeners();
  }

  Future<void> refresh() async {
    try {
      _setRaw(jMap(await engine.call('state')));
    } on Object {
      // offline: the screens say so
    }
  }

  /// The last snapshot as sent: small events (health, a probe, an error) patch it.
  Map<String, Object?> _raw = const {};

  void _patch(Map<String, Object?> changes) {
    if (state == null) return;
    _raw = {..._raw, ...changes};
    state = VpnState.fromJson(_raw);
    notifyListeners();
  }

  void _setRaw(Map<String, Object?> raw) {
    _raw = raw;
    final s = VpnState.fromJson(raw);
    final wasUp = state?.connected ?? false;
    state = s;
    if (!s.connected && wasUp) {
      samples.clear();
      traffic = const Traffic(0, 0);
    }
    if (logLines.isEmpty) logLines.addAll(s.log.reversed.take(80).toList().reversed);
    notifyListeners();
  }

  void _event(EngineEvent e) {
    switch (e.name) {
      case 'state':
        _setRaw(e.map);
      case 'traffic':
        traffic = Traffic.fromJson(e.params);
        samples.add(traffic.rxBps, traffic.txBps);
        notifyListeners();
      case 'health':
        _patch({'health': e.params});
      case 'probe':
        final m = e.map;
        final name = jStr(m['name']);
        _patch({
          'regions': [
            for (final r in jList(_raw['regions'])) jStr(jMap(r)['name']) == name ? {...jMap(r), 'ping': m['ping']} : r,
          ],
        });
      case 'error_action':
        _patch({'error': e.params});
      case 'log':
        logLines.add(LogEntry.fromJson(e.params));
        while (logLines.length > 200) {
          logLines.removeAt(0);
        }
        notifyListeners();
      case 'fix_result':
        final m = e.map;
        final msg = jStr(m['message']);
        if (msg.isNotEmpty) toast(msg, good: jBool(m['ok']));
      case 'notify':
        final m = e.map;
        final msg = [jStr(m['title']), jStr(m['msg'])].where((x) => x.isNotEmpty).join(': ');
        if (msg.isNotEmpty) toast(msg);
      case 'task_done':
        final m = e.map;
        busy.remove(jStr(m['key']));
        final err = jStrN(m['error']);
        if (err != null) toast(err);
        notifyListeners();
      case 'endpoint_report':
        endpointReport = e.map;
        notifyListeners();
      case 'net_repair_start':
        busy.add('net_repair');
        notifyListeners();
      case 'net_repair_done':
        busy.remove('net_repair');
        lastRepair = e.map;
        toast(jBool(e.map['ok']) ? 'Network repaired.' : 'Repair finished with problems. The log has each step.',
            good: jBool(e.map['ok']));
      case 'show':
        onShow?.call(jStr(e.map['window'], 'main'));
      case 'quitting':
        onQuitting?.call();
    }
  }

  // ---------------------------------------------------------------- toasts
  void toast(String text, {bool good = false}) {
    final t = Toast(text, good: good);
    toasts.add(t);
    while (toasts.length > 3) {
      toasts.removeAt(0);
    }
    notifyListeners();
    Timer(Duration(milliseconds: good ? 3800 : 6500), () => dismissToast(t.id));
  }

  void dismissToast(int id) {
    final before = toasts.length;
    toasts.removeWhere((t) => t.id == id);
    if (toasts.length != before) notifyListeners();
  }

  /// Run an action: an `{ok: false}` answer becomes a toast with the engine's sentence; offline says so.
  /// [busyKey]: a long task the engine reports with task_done (the button shows it's running until then).
  Future<Answer?> act(Future<Answer> Function() f, {String? done, String? busyKey}) async {
    if (busyKey != null) {
      busy.add(busyKey);
      notifyListeners();
    }
    try {
      final a = await f();
      if (!a.ok) {
        if (busyKey != null) busy.remove(busyKey);
        toast(a.error.isEmpty ? "NOBAD couldn't do that." : _sentence(a.error));
      } else if (done != null) {
        toast(done, good: true);
      }
      notifyListeners();
      return a;
    } on EngineOffline {
      if (busyKey != null) busy.remove(busyKey);
      toast("NOBAD VPN isn't running. Start it from the Start menu.");
    } on RpcException catch (e) {
      if (busyKey != null) busy.remove(busyKey);
      toast(e.message);
    }
    notifyListeners();
    return null;
  }

  static String _sentence(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

  // ---------------------------------------------------------------- the main actions
  /// The aperture: connect to the target server, or disconnect.
  Future<void> toggle() async {
    final s = state;
    if (s == null) return;
    if (s.connected || s.connecting != null) {
      await act(engine.disconnect);
    } else {
      final pick = selected != null && s.region(selected) != null ? selected : s.target;
      if (pick != null) await act(() => engine.connect(pick));
    }
  }

  Future<void> connect(String name) => act(() => engine.connect(name));

  @override
  void dispose() {
    _sub.cancel();
    engine.link.removeListener(_linked);
    super.dispose();
  }
}
