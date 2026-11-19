/// Activity: the WebView's "t4" tab. Protection check, Session, Exit & protection, Recent sessions (from the state
/// snapshot), and Usage history (`usage {days}`: totals, the daily chart, by server, speed tests, sessions). Same
/// rows and words as app.js protHTML / renderDet / sessHTML and app_ext.js usageRender.
library;

import 'dart:async';
import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../widgets/controls.dart';
import '../../widgets/panels.dart';

String dur(num secs) {
  final s = secs.round();
  if (s < 60) return '${s}s';
  if (s < 3600) return '${s ~/ 60}m ${s % 60}s';
  return '${s ~/ 3600}h ${(s % 3600) ~/ 60}m';
}

String when(num ts) {
  final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
  String two(int v) => v.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)} ${two(d.hour)}:${two(d.minute)}';
}

/// The protection check rows (label, passed: true/false/null unknown, detail), as app.js protHTML.
List<(String, bool?, String)> protectionRows(Map<String, Object?> s, Map<String, Object?> traffic) {
  final active = jStrN(s['active']);
  final r = jList(s['regions']).map(jMap).where((x) => x['name'] == active).firstOrNull;
  final hs = traffic['hs_age'];
  final ex = jMap(s['exit']), home = jMap(s['home']);
  final e = ex.isNotEmpty && ex['error'] == null && ex['disabled'] != true ? ex : null;
  final ks = s['ks_active'] == true;
  return [
    ('Tunnel active', true, active ?? ''),
    ('Fresh handshake', hs is num ? hs < 180 : null, hs is num ? '$hs s ago' : 'waiting'),
    ('All traffic routed', r == null ? null : r['full'] == true, r == null ? '' : (r['full'] == true ? '0.0.0.0/0' : 'split tunnel')),
    ('IPv6 covered', r == null ? null : r['v6'] == true, r == null ? '' : (r['v6'] == true ? '::/0 routed' : 'IPv6 may leak')),
    ('DNS inside tunnel', r == null ? null : (r['dns'] == true || s['dns_active'] == true),
        r == null ? '' : (r['dns'] == true ? 'tunnel DNS' : 'system DNS')),
    ('Exit differs from real IP', e != null && home['ip'] != null ? e['ip'] != home['ip'] : null,
        e != null && home['ip'] != null ? (e['ip'] != home['ip'] ? 'changed' : 'same IP') : 'unknown'),
    ('Kill switch armed', ks, ks ? 'armed' : 'off'),
  ];
}

class ActivityScreen extends StatefulWidget {
  const ActivityScreen({super.key});
  @override
  State<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends State<ActivityScreen> {
  StreamSubscription<EngineEvent>? _sub;
  Map<String, Object?> _state = const {}, _traffic = const {};
  Map<String, Object?>? _usage;
  bool _loading = false, _more = false, _usageFailed = false;
  String _days = '30';

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_sub == null) {
      final engine = AppScope.of(context).engine;
      _sub = engine.events.listen(_event);
      unawaited(engine.call('state').then((s) {
        if (mounted) setState(() => _state = jMap(s));
      }, onError: (Object _) {}));
      unawaited(_load());
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  void _event(EngineEvent e) {
    if (e.name == 'state') {
      _state = e.map;
    } else if (e.name == 'traffic') {
      _traffic = e.map;
    } else {
      return;
    }
    if (mounted) setState(() {});
  }

  Future<void> _load() async {
    if (_loading) return;
    setState(() => _loading = true);
    try {
      final a = Answer.fromJson(await AppScope.of(context).engine.call('usage', {'days': int.parse(_days)}));
      if (!mounted) return;
      setState(() {
        _usageFailed = !a.ok;
        if (a.ok) _usage = a.data;
      });
    } on Object {
      if (mounted) setState(() => _usageFailed = true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(NbSpace.x3),
      child: Align(
        alignment: Alignment.topLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const PageTitle('Activity', sub: 'What protects you right now, and what NOBAD has carried.'),
              const SizedBox(height: NbSpace.x3),
              _protection(context),
              const SizedBox(height: NbSpace.x3),
              _session(context),
              const SizedBox(height: NbSpace.x3),
              _exit(context),
              const SizedBox(height: NbSpace.x3),
              _sessions(context),
              const SizedBox(height: NbSpace.x3),
              _usagePanel(context),
            ],
          ),
        ),
      ),
    );
  }

  Widget _card(String title, List<Widget> children, {Widget? trailing}) {
    final c = NbColors.of(context);
    return NbPanel(
      padding: const EdgeInsets.all(NbSpace.x3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [Expanded(child: Text(title, style: NbType.label(NbSize.title, c.text))), ?trailing]),
          const SizedBox(height: NbSpace.x2),
          ...children,
        ],
      ),
    );
  }

  Widget _kv(String k, String? v) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Text(k, style: NbType.text(NbSize.body, c.muted)),
          const SizedBox(width: NbSpace.x3),
          Expanded(
            child: SelectableText(v == null || v.isEmpty ? '—' : v, textAlign: TextAlign.right, maxLines: 1,
                style: NbType.label(NbSize.body, c.text)),
          ),
        ],
      ),
    );
  }

  Widget _protection(BuildContext context) {
    final c = NbColors.of(context);
    if (_state['connected'] != true) {
      return _card('Protection check', [Text('Connect to a server to run the protection check.', style: NbType.text(NbSize.small, c.muted))]);
    }
    final rows = protectionRows(_state, _traffic);
    final known = rows.where((x) => x.$2 != null).toList(), ok = known.where((x) => x.$2 == true).length, n = known.length;
    final f = n == 0 ? 0.0 : ok / n;
    final tone = f >= .99 ? c.sealed : (f >= .7 ? c.amber : c.blocked);
    final label = f >= .99 ? 'Fully protected' : (f >= .7 ? 'Mostly protected' : 'Needs attention');
    return _card('Protection check', [
      Row(children: [
        SizedBox.square(dimension: 56, child: CustomPaint(painter: _Ring(f, tone, c.line2))),
        const SizedBox(width: NbSpace.x3),
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$ok/$n checks', style: NbType.label(NbSize.lead, tone)),
          Text(label, style: NbType.text(NbSize.small, c.muted)),
        ]),
      ]),
      const SizedBox(height: NbSpace.x2),
      for (final (k, v, t) in rows)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(children: [
            Container(
              width: 18,
              height: 18,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: (v == null ? c.muted : (v ? c.sealed : c.amber)).withValues(alpha: .16),
              ),
              child: Text(v == null ? '–' : (v ? '✓' : '!'),
                  style: NbType.label(NbSize.small, v == null ? c.muted : (v ? c.sealed : c.amber))),
            ),
            const SizedBox(width: 10),
            Expanded(child: Text(k, style: NbType.text(NbSize.body, c.text))),
            Text(t, style: NbType.text(NbSize.small, c.muted)),
          ]),
        ),
    ]);
  }

  Widget _session(BuildContext context) {
    final c = NbColors.of(context);
    final s = _state;
    if (s['connected'] != true && s['connecting'] == null) {
      return _card('Session', [
        _kv('Status', 'Not connected'),
        Text('Endpoint, handshake, traffic and uptime appear here while you are connected.', style: NbType.text(NbSize.small, c.muted)),
      ]);
    }
    final active = jStrN(s['active']) ?? jStrN(s['connecting']);
    final r = jList(s['regions']).map(jMap).where((x) => x['name'] == active).firstOrNull;
    final t = _traffic, hs = t['hs_age'];
    final since = jNum(s['since']);
    return _card('Session', [
      _kv('Status', s['connected'] == true ? 'Protected' : 'Connecting…'),
      _kv('Server', active),
      _kv('Endpoint', jStrN(t['endpoint']) ?? (r != null ? '${r['host']}:${r['port']}' : null)),
      _kv('Last handshake', hs is num ? '$hs s ago' : null),
      _kv('Downloaded', t['rx_total'] is num ? bytes(t['rx_total'] as num) : null),
      _kv('Uploaded', t['tx_total'] is num ? bytes(t['tx_total'] as num) : null),
      _kv('Uptime', s['connected'] == true ? uptime(since, DateTime.now()) : null),
    ]);
  }

  Widget _exit(BuildContext context) {
    final s = _state, st = jMap(s['settings']);
    final ex = jMap(s['exit']);
    final e = ex.isNotEmpty && ex['error'] == null && ex['disabled'] != true ? ex : null;
    final ks = s['ks_active'] == true;
    return _card('Exit & protection', [
      _kv('Exit IP', jStrN(e?['ip'])),
      _kv('Location', e == null ? null : [jStr(e['city']), jStr(e['region']), jStr(e['country'])].where((x) => x.isNotEmpty).join(', ')),
      _kv('Provider', jStrN(e?['org'])),
      _kv('Kill switch', ks ? 'Armed' : (st['kill_switch'] == true ? 'On (arms when connected)' : 'Off')),
      _kv('Auto-repair', st['auto_repair'] == true ? 'On' : 'Off'),
      _kv('Streaming tune', st['stream_tuned'] == true ? 'MTU 1380 · keepalive 25' : 'Off'),
    ]);
  }

  Widget _sessionRow(Map<String, Object?> x) {
    final c = NbColors.of(context);
    final peak = jNum(x['peak_bps']);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(jStr(x['name']), style: NbType.label(NbSize.body, c.text)),
            Text(x['start'] is num ? when(x['start'] as num) : '', style: NbType.text(NbSize.small, c.muted)),
          ]),
        ),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(dur(jNum(x['secs']) ?? 0), style: NbType.data(NbSize.body, c.text)),
          Text('↓ ${bytes(jNum(x['rx']) ?? 0)} · ↑ ${bytes(jNum(x['tx']) ?? 0)}${peak != null && peak > 0 ? ' · peak ${rate(peak)}' : ''}',
              style: NbType.data(NbSize.small, c.muted)),
        ]),
      ]),
    );
  }

  Widget _sessions(BuildContext context) {
    final c = NbColors.of(context);
    final a = [for (final x in jList(_state['sessions']).reversed) jMap(x)];
    return _card('Recent sessions', [
      if (a.isEmpty)
        Text('No sessions yet. They appear here after you disconnect.', style: NbType.text(NbSize.small, c.muted))
      else
        for (final x in a) _sessionRow(x),
    ]);
  }

  Widget _usagePanel(BuildContext context) {
    final c = NbColors.of(context);
    final u = _usage;
    final children = <Widget>[];
    if (u == null) {
      children.add(_usageFailed
          ? Text('Usage history is unavailable.', style: NbType.text(NbSize.small, c.muted))
          : Text('Loading…', style: NbType.text(NbSize.small, c.muted)));
    } else {
      final tot = jMap(u['totals']);
      final daily = [for (final d in jList(u['daily'])) jMap(d)];
      final sp = [for (final x in jList(u['speed'])) jNum(jMap(x)['mbps']) ?? 0];
      final sessions = [for (final x in jList(u['sessions'])) jMap(x)];
      final servers = [for (final x in jList(u['servers'])) jMap(x)];
      children.addAll([
        Wrap(spacing: NbSpace.x6, runSpacing: NbSpace.x2, children: [
          Metric('Downloaded', bytes(jNum(tot['rx']) ?? 0)),
          Metric('Uploaded', bytes(jNum(tot['tx']) ?? 0)),
          Metric('Time connected', dur(jNum(tot['secs']) ?? 0)),
        ]),
        const SizedBox(height: NbSpace.x3),
        Semantics(
          label: 'Daily data usage chart',
          child: SizedBox(height: 110, child: CustomPaint(painter: _DailyPainter(daily, c))),
        ),
        const SizedBox(height: 6),
        Row(children: [
          _Swatch(c.orange, 'Download'),
          const SizedBox(width: NbSpace.x3),
          _Swatch(const Color(0xFFA9AAB2), 'Upload'),
        ]),
        const SizedBox(height: NbSpace.x3),
        Text('By server', style: NbType.label(NbSize.body, c.text)),
        if (servers.isEmpty) Text('No data yet.', style: NbType.text(NbSize.small, c.muted)),
        for (final s in servers.take(8))
          _kv(jStr(s['name']), '${bytes((jNum(s['rx']) ?? 0) + (jNum(s['tx']) ?? 0))} · ${jInt(s['sessions'])}×'),
        const SizedBox(height: NbSpace.x3),
        Text('Speed tests', style: NbType.label(NbSize.body, c.text)),
        if (sp.isEmpty)
          Text('Run a speed test to start the history.', style: NbType.text(NbSize.small, c.muted))
        else ...[
          Semantics(label: 'Speed test history', child: SizedBox(height: 60, child: CustomPaint(painter: _SparkPainter(sp, c.orange)))),
          Text('Latest ${sp.last} Mbps · best ${sp.reduce(math.max)} · average ${(sp.reduce((a, b) => a + b) / sp.length).toStringAsFixed(1)}',
              style: NbType.text(NbSize.small, c.muted)),
        ],
        const SizedBox(height: NbSpace.x3),
        Text('Sessions', style: NbType.label(NbSize.body, c.text)),
        if (sessions.isEmpty) Text('No sessions yet.', style: NbType.text(NbSize.small, c.muted)),
        for (final x in sessions.take(_more ? 100 : 8)) _sessionRow(x),
        if (sessions.length > 8)
          Align(
            alignment: Alignment.centerLeft,
            child: NbButton(_more ? 'Show fewer' : 'Show more', small: true, kind: NbButtonKind.quiet,
                onPressed: () => setState(() => _more = !_more)),
          ),
      ]);
    }
    return _card('Usage history', children, trailing: Row(mainAxisSize: MainAxisSize.min, children: [
      NbSelect(
        value: _days,
        label: 'Range',
        compact: true,
        options: const [('7', 'Last 7 days'), ('30', 'Last 30 days'), ('0', 'All time')],
        onChanged: (v) {
          setState(() => _days = v);
          unawaited(_load());
        },
      ),
      const SizedBox(width: 6),
      NbButton('Refresh', small: true, kind: NbButtonKind.ghost, onPressed: _loading ? null : _load),
    ]));
  }
}

class _Swatch extends StatelessWidget {
  const _Swatch(this.color, this.label);
  final Color color;
  final String label;
  @override
  Widget build(BuildContext context) => Row(mainAxisSize: MainAxisSize.min, children: [
    Container(width: 10, height: 10, decoration: BoxDecoration(color: color, borderRadius: NbRadius.keyAll)),
    const SizedBox(width: 6),
    Text(label, style: NbType.text(NbSize.small, NbColors.of(context).muted)),
  ]);
}

class _Ring extends CustomPainter {
  _Ring(this.f, this.color, this.track);
  final double f;
  final Color color, track;
  @override
  void paint(Canvas canvas, Size size) {
    final r = Rect.fromCircle(center: size.center(Offset.zero), radius: size.width / 2 - 4);
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 6
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(r, 0, math.pi * 2, false, p..color = track);
    if (f > 0) canvas.drawArc(r, -math.pi / 2, math.pi * 2 * f, false, p..color = color);
  }

  @override
  bool shouldRepaint(_Ring o) => o.f != f || o.color != color || o.track != track;
}

/// Daily bars: download (orange) at the bottom, upload (grey) on top; at most 60 bars (days bucketed).
class _DailyPainter extends CustomPainter {
  _DailyPainter(this.daily, this.c);
  final List<Map<String, Object?>> daily;
  final NbColors c;

  @override
  void paint(Canvas canvas, Size size) {
    final tp = TextPainter(textDirection: TextDirection.ltr);
    void label(String t, Offset at, {bool right = false}) {
      tp.text = TextSpan(text: t, style: NbType.data(NbSize.small, c.muted));
      tp.layout();
      tp.paint(canvas, right ? at - Offset(tp.width, 0) : at);
    }

    if (daily.isEmpty) {
      tp.text = TextSpan(text: 'No data yet.', style: NbType.text(NbSize.small, c.muted));
      tp.layout();
      tp.paint(canvas, size.center(Offset.zero) - Offset(tp.width / 2, tp.height / 2));
      tp.dispose();
      return;
    }
    final per = (daily.length / 60).ceil();
    final bars = <(String, double, double)>[];
    for (var i = 0; i < daily.length; i += per) {
      final s = daily.sublist(i, math.min(daily.length, i + per));
      bars.add((jStr(s.first['day']), s.fold(0.0, (a, d) => a + (jNum(d['rx']) ?? 0)), s.fold(0.0, (a, d) => a + (jNum(d['tx']) ?? 0))));
    }
    final mx = math.max(1.0, bars.map((b) => b.$2 + b.$3).reduce(math.max));
    final base = size.height - 16, top = 16.0;
    final step = (size.width - 8) / bars.length, bw = math.max(2.0, step - 2);
    for (var i = 0; i < bars.length; i++) {
      final (_, rx, tx) = bars[i];
      final x = 4 + i * step;
      final hr = rx / mx * (base - top), ht = tx / mx * (base - top);
      canvas.drawRect(Rect.fromLTWH(x, base - hr - ht, bw, ht), Paint()..color = const Color(0xFFA9AAB2));
      canvas.drawRect(Rect.fromLTWH(x, base - hr, bw, hr), Paint()..color = c.orange);
    }
    label(bytes(mx), const Offset(4, 0));
    String md(String d) => d.length >= 10 ? d.substring(5) : d;
    label(md(bars.first.$1), Offset(4, size.height - 14));
    label(md(bars.last.$1), Offset(size.width - 4, size.height - 14), right: true);
    tp.dispose();
  }

  @override
  bool shouldRepaint(_DailyPainter o) => o.daily != daily || o.c != c;
}

class _SparkPainter extends CustomPainter {
  _SparkPainter(this.v, this.color);
  final List<double> v;
  final Color color;
  @override
  void paint(Canvas canvas, Size size) {
    final vs = v.length > 40 ? v.sublist(v.length - 40) : v;
    final mx = math.max(1e-6, vs.reduce(math.max) * 1.15);
    Offset at(int i) => Offset(vs.length == 1 ? size.width / 2 : 4 + i * (size.width - 8) / (vs.length - 1),
        size.height - 4 - vs[i] / mx * (size.height - 8));
    final path = Path()..moveTo(at(0).dx, at(0).dy);
    for (var i = 1; i < vs.length; i++) {
      path.lineTo(at(i).dx, at(i).dy);
    }
    canvas.drawPath(path, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6
      ..color = color);
    for (var i = 0; i < vs.length; i++) {
      canvas.drawCircle(at(i), 2, Paint()..color = color);
    }
  }

  @override
  bool shouldRepaint(_SparkPainter o) => o.v != v || o.color != color;
}
