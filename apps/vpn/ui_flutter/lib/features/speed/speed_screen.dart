/// Speed: the WebView's "t1" tab and its launch diagnostics card. The speed test (`speedtest` -> `speed` /
/// `speed_done`), service reachability (`streamcheck` -> `stream_start` / `stream` / `stream_done`), and the five
/// launch checks (Public IP, Speed test, Service checks, Network health, VALORANT regions), fed by the same events
/// the engine sends after `startup_checks`. Same words as the WebView (nobadvpn/ui/index.html, app.js).
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

/// One launch check: its state (waiting, running, ok, warn, bad, off) and the words after it.
class BootItem {
  const BootItem(this.status, this.detail);
  final String status;
  final String detail;
}

const bootChecks = [
  ('IP', 'Public IP'),
  ('Speed', 'Speed test'),
  ('Services', 'Service checks'),
  ('Network', 'Network health'),
  ('Valorant', 'VALORANT regions'),
];

class SpeedScreen extends StatefulWidget {
  const SpeedScreen({super.key});
  @override
  State<SpeedScreen> createState() => _SpeedScreenState();
}

class _SpeedScreenState extends State<SpeedScreen> {
  StreamSubscription<EngineEvent>? _sub;
  double _mbps = 0, _pct = 0;
  bool _speedBusy = false, _streamBusy = false;
  String? _speedError;
  double? _speedFinal;
  final _services = <String, Map<String, Object?>>{};
  bool _servicesTesting = false;
  final _boot = {for (final (k, _) in bootChecks) k: const BootItem('waiting', 'Waiting…')};

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sub ??= AppScope.of(context).engine.events.listen(_event);
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  void _mark(String k, String status, String detail) => _boot[k] = BootItem(status, detail);

  void _event(EngineEvent e) {
    final p = e.map;
    var changed = true;
    switch (e.name) {
      case 'speed':
        _speedBusy = true;
        _speedError = null;
        _mbps = jNum(p['mbps']) ?? 0;
        _pct = jNum(p['pct']) ?? 0;
        _mark('Speed', 'running', 'Testing…');
      case 'speed_done':
        _speedBusy = false;
        final err = jStrN(p['error']);
        if (err != null) {
          _speedError = err;
          _mark('Speed', 'bad', 'Test failed');
        } else {
          _speedFinal = _mbps = jNum(p['mbps']) ?? 0;
          _pct = 100;
          _mark('Speed', 'ok', '${jNum(p['mbps']) ?? 0} Mbps');
        }
      case 'stream_start':
        _streamBusy = _servicesTesting = true;
        _services.clear();
        _mark('Services', 'running', 'Checking sites…');
      case 'stream':
        _servicesTesting = false;
        _services[jStr(p['id'], '${_services.length}')] = p;
      case 'stream_done':
        _streamBusy = _servicesTesting = false;
        final a = _services.values.toList(), ok = a.where((x) => x['level'] == 'ok').length;
        _mark('Services', ok == a.length ? 'ok' : (ok > 0 ? 'warn' : 'bad'), '$ok / ${a.length} reachable');
      case 'ipinfo':
        final ip = jStrN(p['ip']);
        _mark('IP', ip != null ? 'ok' : 'warn', ip ?? (p['error'] != null ? 'Lookup unavailable' : 'Not available'));
      case 'network_diagnose':
        final issues = [for (final i in jList(p['issues'])) jMap(i)];
        final bad = issues.any((x) => x['level'] == 'bad'), warn = issues.any((x) => x['level'] == 'warn');
        _mark('Network', bad ? 'bad' : (warn ? 'warn' : 'ok'),
            bad ? 'Needs attention' : (warn ? 'Review suggested' : 'Looks healthy'));
      case 'valorant_start':
        _mark('Valorant', 'running', 'Scanning regions…');
      case 'valorant_done':
        final b = jMap(p['best']);
        final reachable = jInt(p['reachable']), count = jInt(p['count']);
        _mark('Valorant', reachable > 0 ? 'ok' : 'warn', reachable > 0
            ? (jNum(b['rtt']) != null ? 'Best ${jNum(b['rtt'])!.round()} ms · ${jStr(b['name'])}' : '$reachable / $count reachable')
            : 'No region answered');
      case 'task_done':
        final key = jStr(p['key']);
        final err = jStrN(p['error']);
        if (key == 'speed') _speedBusy = false;
        if (key == 'stream') _streamBusy = _servicesTesting = false;
        const map = {'speed': 'Speed', 'stream': 'Services', 'network_diagnose': 'Network', 'ipinfo': 'IP',
            'valorant_manual': 'Valorant'};
        final bk = map[key];
        if (bk != null && _boot[bk]!.status == 'running') _mark(bk, 'warn', err != null ? 'Stopped: check failed' : 'Finished');
      default:
        changed = false;
    }
    if (changed && mounted) setState(() {});
  }

  Future<void> _run(String method, {required void Function() busy}) async {
    final vpn = AppScope.of(context).vpn;
    setState(busy);
    final a = await vpn.act(() async => Answer.fromJson(await vpn.engine.call(method)));
    if ((a == null || !a.ok) && mounted) {
      setState(() {
        if (method == 'speedtest') _speedBusy = false;
        if (method == 'streamcheck') _streamBusy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(NbSpace.x3),
      child: Align(
        alignment: Alignment.topLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const PageTitle('Speed', sub: 'Speed test and service reachability through the current connection.'),
              const SizedBox(height: NbSpace.x3),
              _bootCard(c),
              const SizedBox(height: NbSpace.x3),
              _speedCard(c),
              const SizedBox(height: NbSpace.x3),
              _servicesCard(c),
            ],
          ),
        ),
      ),
    );
  }

  Widget _bootCard(NbColors c) {
    final finished = _boot.values.where((b) => b.status != 'waiting' && b.status != 'running').length;
    final allWaiting = _boot.values.every((b) => b.status == 'waiting');
    final state = allWaiting ? 'Starting' : (finished == _boot.length ? 'Scan complete' : '$finished / ${_boot.length} complete');
    return NbPanel(
      padding: const EdgeInsets.all(NbSpace.x3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Head(title: 'Launch diagnostics', note: 'Automatic one-time checks from this launch', trailing: Text(state,
              key: const ValueKey('bootState'), style: NbType.label(NbSize.small, c.muted))),
          const SizedBox(height: NbSpace.x2),
          Wrap(
            spacing: NbSpace.x2,
            runSpacing: NbSpace.x2,
            children: [
              for (final (k, label) in bootChecks) _BootTile(label: label, item: _boot[k]!),
            ],
          ),
        ],
      ),
    );
  }

  Widget _speedCard(NbColors c) {
    final v = _mbps;
    final text = v >= 100 ? '${v.round()}' : v.toStringAsFixed(1);
    final reached = _speedFinal ?? (_speedBusy ? null : 0.0);
    return NbPanel(
      padding: const EdgeInsets.all(NbSpace.x3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _Head(title: 'Speed test', note: 'Through the current connection'),
          const SizedBox(height: NbSpace.x3),
          Center(
            child: SizedBox(
              width: 260,
              height: 140,
              child: Semantics(
                label: 'Speed',
                value: '$text Mbps',
                child: CustomPaint(
                  painter: _GaugePainter(math.min(1, v / 100), _pct / 100, c),
                  child: Align(
                    alignment: const Alignment(0, .7),
                    child: Text.rich(
                      TextSpan(children: [
                        TextSpan(text: text, style: NbType.data(NbSize.field, c.text)),
                        TextSpan(text: ' Mbps', style: NbType.text(NbSize.small, c.muted)),
                      ]),
                    ),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: NbSpace.x2),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (final (label, need) in const [('SD', 3.0), ('HD', 8.0), ('4K', 25.0)]) ...[
                _Chip(label: label, on: reached != null && reached >= need),
                const SizedBox(width: 6),
              ],
            ],
          ),
          if (_speedError != null) ...[
            const SizedBox(height: NbSpace.x2),
            Notice(kind: NoticeKind.warn, title: 'Test failed', detail: _speedError!),
          ],
          const SizedBox(height: NbSpace.x3),
          Center(
            child: NbButton(_speedBusy ? 'Testing…' : 'Run speed test',
                onPressed: _speedBusy ? null : () => _run('speedtest', busy: () {
                      _speedBusy = true;
                      _speedError = null;
                      _speedFinal = null;
                    })),
          ),
        ],
      ),
    );
  }

  Widget _servicesCard(NbColors c) {
    final rows = _services.values.toList();
    return NbPanel(
      padding: const EdgeInsets.all(NbSpace.x3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Head(
            title: 'Service reachability',
            trailing: NbButton(_streamBusy ? 'Checking…' : 'Check', small: true, kind: NbButtonKind.ghost,
                onPressed: _streamBusy ? null : () => _run('streamcheck', busy: () => _streamBusy = true)),
          ),
          const SizedBox(height: 6),
          if (_servicesTesting && rows.isEmpty)
            _ServiceRow(name: 'Testing…', note: '', level: 'warn', ms: null)
          else if (rows.isEmpty)
            Text('Press Check to test streaming sites through your current connection.',
                style: NbType.text(NbSize.small, c.muted))
          else
            for (final s in rows)
              _ServiceRow(name: jStr(s['name']), note: jStr(s['note']), level: jStr(s['level'], 'warn'), ms: jNum(s['ms'])),
          const SizedBox(height: NbSpace.x2),
          Text("Reachable means the site answered from this exit. It doesn't guarantee a particular title will play.",
              style: NbType.text(NbSize.small, c.dim, height: 1.45)),
        ],
      ),
    );
  }
}

class _Head extends StatelessWidget {
  const _Head({required this.title, this.note, this.trailing});
  final String title;
  final String? note;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: NbType.label(NbSize.title, c.text)),
              if (note != null) Text(note!, style: NbType.text(NbSize.small, c.muted, height: 1.45)),
            ],
          ),
        ),
        ?trailing,
      ],
    );
  }
}

Color levelColor(NbColors c, String level) => switch (level) {
  'ok' || 'good' => c.sealed,
  'warn' || 'running' => c.amber,
  'bad' => c.blocked,
  _ => c.dim,
};

class _BootTile extends StatelessWidget {
  const _BootTile({required this.label, required this.item});
  final String label;
  final BootItem item;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Semantics(
      label: '$label: ${item.detail}',
      child: Container(
        width: 140,
        padding: const EdgeInsets.all(NbSpace.x2),
        decoration: BoxDecoration(color: c.card, borderRadius: NbRadius.rowAll, border: Border.all(color: c.line)),
        child: Row(
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: item.status == 'off' || item.status == 'waiting' ? null : levelColor(c, item.status),
                border: item.status == 'off' || item.status == 'waiting' ? Border.all(color: c.muted, width: 1.5) : null,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: NbType.label(NbSize.small, c.text)),
                  Text(item.detail, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.text(NbSize.small, c.muted)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.on});
  final String label;
  final bool on;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return AnimatedContainer(
      duration: NbMotion.of(context, NbMotion.base),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        color: on ? c.sealed : null,
        borderRadius: NbRadius.pillAll,
        border: Border.all(color: on ? c.sealed : c.line2),
      ),
      child: Text(label, style: NbType.label(NbSize.small, on ? c.bg : c.muted)),
    );
  }
}

class _ServiceRow extends StatelessWidget {
  const _ServiceRow({required this.name, required this.note, required this.level, required this.ms});
  final String name, note, level;
  final double? ms;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Container(width: 9, height: 9, decoration: BoxDecoration(shape: BoxShape.circle, color: levelColor(c, level))),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name, style: NbType.label(NbSize.body, c.text)),
                if (note.isNotEmpty) Text(note, style: NbType.text(NbSize.small, c.muted)),
              ],
            ),
          ),
          if (ms != null) Text('${ms!.round()} ms', style: NbType.data(NbSize.small, c.muted)),
        ],
      ),
    );
  }
}

/// The half-circle gauge: the track, the value (0..1 of 100 Mbps) and a thin progress line under it.
class _GaugePainter extends CustomPainter {
  _GaugePainter(this.value, this.progress, this.c);
  final double value, progress;
  final NbColors c;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height - 10);
    final r = math.min(size.width / 2, size.height) - 12;
    final rect = Rect.fromCircle(center: center, radius: r);
    final track = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 10
      ..strokeCap = StrokeCap.round
      ..color = c.line2;
    canvas.drawArc(rect, math.pi, math.pi, false, track);
    if (value > 0) {
      canvas.drawArc(rect, math.pi, math.pi * value.clamp(0, 1), false, track..color = c.orange);
    }
    if (progress > 0 && progress < 1) {
      canvas.drawLine(Offset(center.dx - r, size.height - 2), Offset(center.dx - r + 2 * r * progress, size.height - 2),
          Paint()
            ..strokeWidth = 2
            ..color = c.orangeA(.6));
    }
  }

  @override
  bool shouldRepaint(_GaugePainter o) => o.value != value || o.progress != progress || o.c != c;
}
