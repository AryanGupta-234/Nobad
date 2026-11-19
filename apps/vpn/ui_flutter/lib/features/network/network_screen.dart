/// Network: the WebView's "t5" tab. The Evil Twin trust grade of the network you're on (eviltwin.js), Network
/// health · Plain-English diagnosis (`network_diagnose`), Clear DNS cache (`flush_dns`), VALORANT · Global server check
/// (`valorant_probe`), a custom game endpoint (`gaming_probe`), and Test connectivity (`reach_test`). Every result is
/// a measurement the engine just made; the words are the WebView's.
library;

import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../widgets/controls.dart';
import '../../widgets/panels.dart';

const gradeNote = {
  'A': 'Looks safe',
  'B': 'Mostly safe',
  'C': 'Be careful',
  'D': 'Risky: use the VPN',
  'F': 'Under attack: use the VPN',
};

String ago(num ts, DateTime now) {
  final s = (now.millisecondsSinceEpoch / 1000 - ts).round().clamp(0, 1 << 30);
  return s < 60 ? 'just now' : (s < 3600 ? '${(s / 60).round()} min ago' : '${(s / 3600).round()} h ago');
}

class NetworkScreen extends StatefulWidget {
  const NetworkScreen({super.key});
  @override
  State<NetworkScreen> createState() => _NetworkScreenState();
}

class _NetworkScreenState extends State<NetworkScreen> {
  StreamSubscription<EngineEvent>? _sub;
  Map<String, Object?> _state = const {};
  Map<String, Object?>? _et, _diag, _game, _reach, _valoDone;
  final _valo = <Map<String, Object?>>[];
  int? _valoTotal;
  bool _etBusy = false, _etOpen = false, _diagBusy = false, _flushBusy = false, _valoBusy = false, _gameBusy = false,
      _reachBusy = false;
  final _host = TextEditingController(text: '151.106.246.1');

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_sub == null) {
      final engine = AppScope.of(context).engine;
      _sub = engine.events.listen(_event);
      unawaited(engine.call('state').then((s) {
        if (mounted) setState(() => _takeState(jMap(s)));
      }, onError: (Object _) {}));
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    _host.dispose();
    super.dispose();
  }

  void _takeState(Map<String, Object?> s) {
    _state = s;
    final et = s['eviltwin'];
    if (et is Map && (_et == null || (jNum(et['ts']) ?? 0) > (jNum(_et!['ts']) ?? 0))) _et = jMap(et);
  }

  void _event(EngineEvent e) {
    final p = e.map;
    switch (e.name) {
      case 'state':
        _takeState(p);
      case 'et_report':
        _et = p;
        _etBusy = false;
      case 'network_diagnose':
        _diag = p;
        _diagBusy = false;
      case 'valorant_start':
        _valoBusy = true;
        _valo.clear();
        _valoDone = null;
        _valoTotal = jInt(p['total']);
      case 'valorant_result':
        _valo.add(p);
      case 'valorant_done':
        _valoBusy = false;
        _valoDone = p;
      case 'gaming_probe':
        _game = p;
        _gameBusy = false;
      case 'reach_report':
        _reach = p;
        _reachBusy = false;
      case 'task_done':
        final key = jStr(p['key']), err = jStrN(p['error']);
        switch (key) {
          case 'et_run':
            if (_etBusy && err != null) AppScope.of(context).vpn.toast('The check stopped: $err');
            _etBusy = false;
          case 'network_diagnose':
            _diagBusy = false;
          case 'flush_dns':
            _flushBusy = false;
          case 'valorant_manual':
            _valoBusy = false;
          case 'gaming':
            _gameBusy = false;
          case 'reach':
            _reachBusy = false;
        }
      default:
        return;
    }
    if (mounted) setState(() {});
  }

  Future<void> _run(String method, void Function(bool) busy, {Map<String, Object?> params = const {}}) async {
    final vpn = AppScope.of(context).vpn;
    setState(() => busy(true));
    final a = await vpn.act(() async => Answer.fromJson(await vpn.engine.call(method, params)));
    if ((a == null || !a.ok) && mounted) setState(() => busy(false));
  }

  Map<String, Object?> get _settings => jMap(_state['settings']);

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
              const PageTitle('Network', sub: "A quick look at the network you're on. Nothing here changes Windows settings."),
              const SizedBox(height: NbSpace.x3),
              _etCard(c),
              const SizedBox(height: NbSpace.x3),
              _healthCard(c),
              const SizedBox(height: NbSpace.x3),
              _valoCard(c),
              const SizedBox(height: NbSpace.x3),
              _reachCard(c),
            ],
          ),
        ),
      ),
    );
  }

  // ---------------------------------------------------------------- Evil Twin
  Widget _etCard(NbColors c) {
    final r = _et;
    final head = _Head(
      title: 'Evil Twin · network trust check',
      note: 'Is this network what it claims to be? Checks DNS, the router, the Wi-Fi itself and HTTPS in about 10 seconds.',
      trailing: NbButton(_etBusy ? 'Checking…' : (r != null ? 'Check again' : 'Check now'), small: true, kind: NbButtonKind.ghost,
          onPressed: _etBusy ? null : () => _run('et_run', (b) => _etBusy = b)),
    );
    final body = <Widget>[];
    if (_etBusy && r == null) {
      body.add(_Empty("Checking DNS, the router, the Wi-Fi and HTTPS…"));
    } else if (r == null) {
      body.add(_Empty(_settings['et_enabled'] == false
          ? 'The automatic check is off (Settings → Network safety). Press Check now to grade this network.'
          : 'Runs by itself whenever you join a network. Press Check now to grade this one.'));
    } else if (r['ok'] != true) {
      body.add(Notice(kind: NoticeKind.warn, title: jStr(r['error'], "The check couldn't finish.")));
    } else {
      final g = jStr(r['grade']);
      final tone = g == 'A' || g == 'B' ? c.sealed : (g == 'C' ? c.amber : c.blocked);
      final checks = [for (final x in jList(r['checks'])) jMap(x)];
      final shown = _etOpen ? checks : checks.where((x) => x['state'] == 'fail' || x['state'] == 'warn').toList();
      final passed = checks.where((x) => x['state'] == 'pass').length, total = checks.where((x) => x['state'] != 'skip').length;
      final thr = jStr(_settings['et_vpn_below'], 'C');
      final kind = r['kind'] == 'wifi' ? ' · Wi-Fi' : (r['kind'] == 'wired' ? ' · wired' : '');
      body.add(Container(
        padding: const EdgeInsets.all(NbSpace.x3),
        decoration: BoxDecoration(color: tone.withValues(alpha: .07), borderRadius: NbRadius.rowAll, border: Border.all(color: tone.withValues(alpha: .4))),
        child: Row(
          children: [
            Semantics(
              label: 'Grade $g',
              child: Container(
                width: 44,
                height: 44,
                alignment: Alignment.center,
                decoration: BoxDecoration(color: tone, borderRadius: NbRadius.controlAll),
                child: Text(g, style: NbType.display(NbSize.page, c.bg)),
              ),
            ),
            const SizedBox(width: NbSpace.x3),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(gradeNote[g] ?? '', style: NbType.label(NbSize.title, c.text)),
                  Text('${jStr(r['network'])}$kind${r['trusted'] == true ? ' · trusted' : ''}', style: NbType.text(NbSize.small, c.muted)),
                  if (jStr(r['summary']).isNotEmpty) Text(jStr(r['summary']), style: NbType.text(NbSize.small, c.muted)),
                ],
              ),
            ),
            Text.rich(TextSpan(children: [
              TextSpan(text: '${jInt(r['score'])}', style: NbType.data(NbSize.field, c.text)),
              TextSpan(text: '/100', style: NbType.text(NbSize.small, c.muted)),
            ])),
          ],
        ),
      ));
      body.add(const SizedBox(height: NbSpace.x2));
      final connected = _state['connected'] == true;
      if (r['action'] == 'connected') {
        body.add(Notice(kind: NoticeKind.info, title: 'NOBAD connected the VPN because this network graded below $thr.'));
      } else if ((g == 'D' || g == 'F') && !connected) {
        body.add(Notice(
          kind: NoticeKind.bad,
          title: "Don't sign in to anything on this network without the VPN.",
          actions: [NoticeAction('Connect NOBAD', () => AppScope.of(context).vpn.toggle(), primary: true)],
        ));
      } else if (r['vpn_connected'] == true) {
        body.add(_Note('NOBAD VPN is connected, so DNS and HTTPS checks were skipped: that traffic already goes through the tunnel.'));
      }
      if (shown.isEmpty) {
        body.add(Notice(kind: NoticeKind.info, title: 'Every check passed', detail: '$passed / $total checks passed.'));
      } else {
        for (final x in shown) {
          body.add(_EtRow(x));
        }
      }
      body.add(const SizedBox(height: NbSpace.x2));
      body.add(Row(
        children: [
          NbButton('${_etOpen ? 'Show problems only' : 'Show all checks'} (${checks.length})', small: true, kind: NbButtonKind.quiet,
              onPressed: () => setState(() => _etOpen = !_etOpen)),
          const Spacer(),
          Flexible(
            child: Text(
              'Measured ${ago(jNum(r['ts']) ?? 0, DateTime.now())} · ${jStr(r['took_s'] is num ? '${r['took_s']}' : r['took_s'])} s · '
              'VPN turns on below ${thr == 'off' ? 'never' : thr}',
              textAlign: TextAlign.right,
              style: NbType.text(NbSize.small, c.dim),
            ),
          ),
        ],
      ));
    }
    return _Card(children: [head, const SizedBox(height: NbSpace.x2), ...body]);
  }

  // ---------------------------------------------------------------- network health
  Widget _healthCard(NbColors c) {
    final d = _diag;
    final gw = jMap(d?['gateway_ping']), inet = jMap(d?['internet_ping']);
    String ping(Map<String, Object?> m) => jNum(m['rtt']) == null ? (d == null ? '—' : 'No reply') : '${jNum(m['rtt'])!.round()} ms';
    return _Card(children: [
      const _Head(
        title: 'Network health · Plain-English diagnosis',
        note: 'A quick check of your router, internet connection and DNS. It does not change Windows settings.',
      ),
      const SizedBox(height: NbSpace.x2),
      Wrap(spacing: NbSpace.x2, children: [
        NbButton(_diagBusy ? 'Checking…' : 'Run network check',
            onPressed: _diagBusy ? null : () => _run('network_diagnose', (b) {
                  _diagBusy = b;
                  if (b) _diag = null;
                })),
        NbButton(_flushBusy ? 'Clearing…' : 'Clear DNS cache', kind: NbButtonKind.ghost,
            onPressed: _flushBusy ? null : () => _run('flush_dns', (b) => _flushBusy = b)),
      ]),
      const SizedBox(height: NbSpace.x3),
      Wrap(spacing: NbSpace.x6, runSpacing: NbSpace.x2, children: [
        Metric('Router', d == null ? '—' : ping(gw)),
        Metric('Internet', d == null ? '—' : ping(inet)),
        Metric('DNS lookup', d == null ? '—' : (d['dns_ok'] == true ? '${jInt(d['dns_ms'])} ms' : 'Failed')),
      ]),
      const SizedBox(height: NbSpace.x3),
      if (_diagBusy && d == null)
        _Empty('Checking router, internet and DNS…')
      else if (d == null)
        _Empty('Run a check to see what is working and what may need attention.')
      else
        for (final i in jList(d['issues']))
          Padding(
            padding: const EdgeInsets.only(bottom: NbSpace.x2),
            child: _Issue(jMap(i)),
          ),
    ]);
  }

  // ---------------------------------------------------------------- VALORANT and custom endpoints
  Widget _valoCard(NbColors c) {
    final done = _valoDone;
    final best = jMap(done?['best']);
    return _Card(children: [
      _Head(
        title: 'VALORANT · Global server check',
        note: 'Checks all listed Riot regions. Mumbai/Singapore use community-reported Riot edge IPs; other regions use '
            'nearby cloud TCP estimates, not actual match ping.',
        trailing: NbButton(_valoBusy ? 'Checking…' : 'Refresh all', small: true, kind: NbButtonKind.ghost,
            onPressed: _valoBusy ? null : () => _run('valorant_probe', (b) => _valoBusy = b)),
      ),
      const SizedBox(height: NbSpace.x3),
      Wrap(spacing: NbSpace.x6, runSpacing: NbSpace.x2, children: [
        Metric('Locations', done != null ? '${jInt(done['count'])}' : (_valoTotal != null ? '$_valoTotal' : '—')),
        Metric('Reachable', done != null ? '${jInt(done['reachable'])}' : (_valoBusy ? 'Checking…' : '—')),
        Metric('Best ping', jNum(best['rtt']) != null ? '${jNum(best['rtt'])!.round()} ms' : '—'),
      ]),
      const SizedBox(height: NbSpace.x2),
      if (_valo.isEmpty)
        _Empty(_valoBusy
            ? 'Checking all VALORANT regions…'
            : 'No VALORANT region check yet. Press Refresh all, or turn on Settings → Run extra checks at startup.')
      else
        for (final q in _valo) _ValoRow(q),
      const SizedBox(height: NbSpace.x2),
      _Note(jStr(done?['note'], 'Actual in-game ping can differ. Some Riot game endpoints intentionally do not answer ICMP.')),
      const SizedBox(height: NbSpace.x3),
      Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(child: NbTextBox(controller: _host, label: '', hint: 'Custom game endpoint IP or hostname', maxLength: 253)),
          const SizedBox(width: NbSpace.x2),
          NbButton(_gameBusy ? 'Testing…' : 'Test custom', kind: NbButtonKind.ghost,
              onPressed: _gameBusy
                  ? null
                  : () => _run('gaming_probe', (b) {
                        _gameBusy = b;
                        if (b) _game = null;
                      }, params: {'host': _host.text.trim()})),
        ],
      ),
      if (_gameBusy && _game == null) ...[const SizedBox(height: NbSpace.x2), _Empty('Testing endpoint reachability…')],
      if (_game != null) ...[const SizedBox(height: NbSpace.x2), _gameResult(_game!)],
    ]);
  }

  Widget _gameResult(Map<String, Object?> q) {
    if (q['ok'] != true) {
      return Notice(kind: NoticeKind.warn, title: 'Could not test this address', detail: jStr(q['error'], 'Check the address'));
    }
    final rtt = jNum(q['rtt']), loss = jNum(q['loss']) ?? 0, jitter = jNum(q['jitter']);
    return Notice(
      kind: loss >= 20 ? NoticeKind.warn : NoticeKind.info,
      title: '${jStr(q['host'])} · ${rtt == null ? 'No ping reply' : '${rtt.round()} ms'}',
      detail: 'Packet loss: ${loss.round()}%${jitter != null ? ' · Jitter: ${jitter.round()} ms' : ''}\n'
          '${jStr(q['verdict'])}\nTest address: ${jStr(q['resolved_ip'])}',
    );
  }

  // ---------------------------------------------------------------- connectivity
  Widget _reachCard(NbColors c) {
    final r = _reach;
    return _Card(children: [
      _Head(
        title: 'Test connectivity',
        note: 'Checks every service NOBAD uses on this network and shows which route works.',
        trailing: NbButton(_reachBusy ? 'Testing…' : 'Test', small: true, kind: NbButtonKind.ghost,
            onPressed: _reachBusy ? null : () => _run('reach_test', (b) => _reachBusy = b)),
      ),
      const SizedBox(height: NbSpace.x2),
      if (r == null)
        _Empty(_reachBusy ? 'Testing every service…' : 'Press Test to check the services NOBAD uses from this network.')
      else
        for (final s in jList(r['services']))
          _ReachRow(jMap(s)),
    ]);
  }
}

class _Card extends StatelessWidget {
  const _Card({required this.children});
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => NbPanel(
    padding: const EdgeInsets.all(NbSpace.x3),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
  );
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
        if (trailing != null) ...[const SizedBox(width: NbSpace.x2), trailing!],
      ],
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
      decoration: BoxDecoration(borderRadius: NbRadius.rowAll, border: Border.all(color: c.line2)),
      child: Text(text, textAlign: TextAlign.center, style: NbType.text(NbSize.small, c.muted, height: 1.45)),
    );
  }
}

class _Note extends StatelessWidget {
  const _Note(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Text(text, style: NbType.text(NbSize.small, NbColors.of(context).dim, height: 1.45));
}

class _Issue extends StatelessWidget {
  const _Issue(this.i);
  final Map<String, Object?> i;
  @override
  Widget build(BuildContext context) {
    final level = jStr(i['level']);
    return Notice(
      kind: level == 'bad' ? NoticeKind.bad : (level == 'warn' ? NoticeKind.warn : NoticeKind.info),
      title: jStr(i['title']),
      detail: '${jStr(i['simple'])}\n${jStr(i['impact'])}\nTry this: ${jStr(i['suggestion'])}',
    );
  }
}

class _EtRow extends StatelessWidget {
  const _EtRow(this.x);
  final Map<String, Object?> x;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final st = jStr(x['state']);
    final tone = switch (st) {
      'pass' => c.sealed,
      'warn' => c.amber,
      'fail' => c.blocked,
      _ => c.muted,
    };
    final icon = const {'pass': '✓', 'warn': '!', 'fail': '✕', 'skip': '–'}[st] ?? '?';
    final ev = [for (final v in jList(x['evidence']).take(4)) '$v'];
    final pts = jInt(x['points']);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 18,
            height: 18,
            alignment: Alignment.center,
            decoration: BoxDecoration(shape: BoxShape.circle, color: tone),
            child: Text(icon, style: NbType.label(NbSize.small, c.bg)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(jStr(x['title']), style: NbType.label(NbSize.body, c.text)),
                if (jStr(x['detail']).isNotEmpty) Text(jStr(x['detail']), style: NbType.text(NbSize.small, c.muted)),
                if (ev.isNotEmpty && st != 'pass')
                  for (final v in ev) Text(v, style: NbType.data(NbSize.small, c.muted)),
              ],
            ),
          ),
          if (pts > 0 && st != 'pass' && st != 'skip') Text('−$pts', style: NbType.label(NbSize.small, tone)),
        ],
      ),
    );
  }
}

class _ValoRow extends StatelessWidget {
  const _ValoRow(this.q);
  final Map<String, Object?> q;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final rtt = jNum(q['rtt']);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 3,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${jStr(q['region'])} · ${jStr(q['name'])}', style: NbType.label(NbSize.body, c.text)),
                Text('${jStr(q['method'], 'Pending')} · ${jStr(q['target'])}', style: NbType.text(NbSize.small, c.muted)),
              ],
            ),
          ),
          SizedBox(
            width: 70,
            child: Text(rtt == null ? '—' : '${rtt.round()} ms', textAlign: TextAlign.right,
                style: NbType.data(NbSize.body, q['kind'] == 'riot-edge' ? c.text : c.muted)),
          ),
          const SizedBox(width: NbSpace.x3),
          Expanded(flex: 3, child: Text(jStr(q['note']), style: NbType.text(NbSize.small, c.dim))),
        ],
      ),
    );
  }
}

class _ReachRow extends StatelessWidget {
  const _ReachRow(this.s);
  final Map<String, Object?> s;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final ok = s['status'] == 'ok';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 9,
            height: 9,
            margin: const EdgeInsets.only(top: 4),
            decoration: BoxDecoration(shape: BoxShape.circle, color: ok ? c.sealed : c.blocked),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(jStr(s['label']), style: NbType.label(NbSize.body, c.text)),
                Text(jStr(s['explain']), style: NbType.text(NbSize.small, c.muted)),
              ],
            ),
          ),
          Text(ok ? jStr(s['route'], 'direct') : 'unreachable', style: NbType.data(NbSize.small, ok ? c.text : c.blocked)),
        ],
      ),
    );
  }
}
