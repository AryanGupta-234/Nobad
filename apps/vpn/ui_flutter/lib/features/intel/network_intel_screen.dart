/// Network Intelligence (the WebView's tab t6, nobadvpn/ui/netintel.js): evidence-based diagnostics for the network,
/// DNS, provider and VPN. Everything shown comes from a measurement the engine just made (ni_* methods and events);
/// nothing is computed or guessed here. Same panes, words and actions as the WebView.
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
import '../../widgets/dialogs.dart';
import '../../widgets/panels.dart';
import '../actions.dart';

const _panes = [
  ('overview', 'Overview'),
  ('sites', 'Sites'),
  ('dns', 'DNS'),
  ('ip', 'IPv4 / IPv6'),
  ('vpn', 'VPN'),
  ('history', 'History'),
];

const _busyWords = {
  'investigate': 'Testing DNS, connection, secure connection and the page…',
  'overview': 'Analyzing your network…',
  'lookup': 'Asking every resolver…',
  'vpn': 'Checking the tunnel…',
};

/// The verdict names (netintel.js V).
const verdicts = {
  'no-address': 'Site is offline everywhere',
  'http-block-page': 'Replaced by a block page',
  'http-403': 'Site refuses access',
  'http-challenge': 'Bot check in the way',
  'http-404': 'Page not found',
  'http-5xx': "Site's server is failing",
  'http-no-answer': "Site doesn't send the page",
  'tls-cert-invalid': 'Certificate for another site',
  'unverified': "Couldn't load the page",
  'references-unreachable': "Can't compare DNS",
  'dns-filtering': 'Blocked by DNS',
  'sni-filtering': 'Blocked by site name (SNI)',
  'ip-unreachable': 'Real addresses unreachable',
  'dns-interception': 'DNS intercepted',
  'http-451': 'Unavailable for legal reasons',
  'resolver-failed': 'Resolver failing',
  'resolver-error': 'Resolver error',
  'os-resolution-failed': "Windows can't resolve it",
  'tls-failed': 'TLS failing',
  'ipv6-path-broken': 'IPv6 path broken',
  'dns-divergence': 'DNS answers differ',
  'name-does-not-exist': 'Name does not exist',
  'local-network': 'No internet on this PC',
  'ok': 'Reachable, nothing filtered',
};

/// One plain answer first (netintel.js STATUS): label, tone, sentence.
const statuses = {
  'blocked': ('Blocked', 'bad', 'Your network (or your provider) stops this site from opening.'),
  'not-blocked-here': ('Not blocked on this PC', 'warn', 'A resolver on this network filters it, but this PC already gets the real address.'),
  'restricted': ('Restricted by the site', 'warn', "The site answers but refuses visitors like you. This isn't your network."),
  'site-problem': ('Problem is the site', 'warn', 'Nothing on your network blocks it: the site itself is down, moved or broken.'),
  'open': ('Opens normally', 'good', 'The page loaded from this network. If your browser still fails, clear its cache or try another browser.'),
  'offline': ('No internet', 'bad', 'This PC has no route to the internet.'),
  'unknown': ('Not conclusive', 'warn', "NOBAD couldn't load the page, so it can't say for sure."),
};
const _steps = {'dns': 'Name to address', 'tcp': 'Connection', 'tls': 'Secure connection', 'http': 'Page', 'http80': 'Plain HTTP'};
const _fixStates = {
  'applied': 'Fixed',
  'refused': 'Not changed',
  'rolled_back': 'Undone automatically',
  'failed': 'Could not change',
  'busy': 'Busy',
  'rolled_back_by_user': 'Undone',
};

String _ago(Object? ts) {
  final t = jNum(ts);
  if (t == null) return '—';
  final s = (DateTime.now().millisecondsSinceEpoch / 1000 - t).round().clamp(0, 1 << 31);
  return s < 60 ? '$s s' : (s < 3600 ? '${(s / 60).round()} min' : '${(s / 3600).round()} h');
}

class NetworkIntelScreen extends StatefulWidget {
  const NetworkIntelScreen({super.key});
  @override
  State<NetworkIntelScreen> createState() => _NetworkIntelScreenState();
}

class _NetworkIntelScreenState extends State<NetworkIntelScreen> {
  String _pane = 'overview';
  Map<String, Object?>? _ov, _inv, _fix, _lookup, _vpn, _hist;
  final _busy = <String>{};
  bool _fixAuto = false;
  bool? _autoPending;
  final _site = TextEditingController();
  final _name = TextEditingController();
  final _types = <String>{'A', 'AAAA', 'CNAME'};
  StreamSubscription<EngineEvent>? _sub;
  AppNav? _nav;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final scope = AppScope.of(context);
      _sub = scope.engine.events.listen(_event);
      (_nav = scope.nav).addListener(_asked);
      if (_ov == null) _go('overview'); // the overview runs once when the screen opens
      _asked();
    });
  }

  /// "Investigate example.com" from the command palette.
  void _asked() {
    if (!mounted) return;
    final q = AppScope.of(context).nav.takeAsk('investigate');
    if (q == null) return;
    setState(() {
      _pane = 'sites';
      _site.text = q;
    });
    _go('investigate');
  }

  @override
  void dispose() {
    _nav?.removeListener(_asked);
    _sub?.cancel();
    _site.dispose();
    _name.dispose();
    super.dispose();
  }

  void _event(EngineEvent e) {
    if (!mounted) return;
    final p = e.map;
    switch (e.name) {
      case 'ni_overview':
        setState(() {
          _busy.remove('overview');
          _ov = p;
        });
      case 'ni_investigation':
        setState(() {
          _busy.remove('investigate');
          _inv = p;
        });
      case 'ni_lookup':
        setState(() {
          _busy.remove('lookup');
          _lookup = p;
        });
      case 'ni_vpn':
        setState(() {
          _busy.remove('vpn');
          _vpn = p;
        });
      case 'ni_fix_start':
        setState(() {
          _busy.add('fix');
          _fixAuto = jBool(p['auto']);
          _fix = null;
        });
      case 'ni_fix':
        setState(() {
          _busy.remove('fix');
          _fix = p;
        });
        if (p['state'] == 'applied') AppScope.of(context).vpn.toast('Site unblocked', good: true);
      case 'task_done':
        final k = const {'ni_overview': 'overview', 'ni_investigate': 'investigate', 'ni_lookup': 'lookup', 'ni_vpn': 'vpn', 'ni_fix': 'fix'}[p['key']];
        if (k == null) return;
        final stuck = _busy.contains(k) || (k == 'investigate' && _busy.contains('fix') && _fixAuto);
        if (stuck) {
          setState(() {
            _busy.remove(k);
            if (k == 'investigate' && _fixAuto) _busy.remove('fix');
          });
          final err = jStrN(p['error']);
          if (err != null) AppScope.of(context).vpn.toast('The check stopped: $err');
        }
    }
  }

  /// Start a measurement: the answer only says it started; the result comes as an event.
  Future<void> _call(String method, Map<String, Object?> params, String key) async {
    final scope = AppScope.of(context);
    setState(() => _busy.add(key));
    try {
      final a = Answer.fromJson(await scope.engine.call(method, params));
      if (!a.ok) {
        if (mounted) setState(() => _busy.remove(key));
        scope.vpn.toast(a.error.isEmpty ? 'Failed' : a.error);
      }
    } on Object catch (e) {
      if (mounted) setState(() => _busy.remove(key));
      scope.vpn.toast(e is RpcException ? e.message : "NOBAD VPN isn't running. Start it from the Start menu.");
    }
  }

  Future<void> _go(String what, [Map<String, Object?> extra = const {}]) async {
    final scope = AppScope.of(context);
    switch (what) {
      case 'overview':
        await _call('ni_overview', const {}, 'overview');
      case 'investigate':
        setState(() => _fix = null);
        await _call('ni_investigate', {'target': _site.text.trim()}, 'investigate');
      case 'lookup':
        await _call('ni_lookup', {'name': _name.text.trim(), 'types': [for (final t in _dnsTypes) if (_types.contains(t)) t]}, 'lookup');
      case 'vpn':
        await _call('ni_vpn', const {}, 'vpn');
      case 'fix':
        final inv = _inv;
        if (inv == null || _busy.contains('fix')) return;
        final ok = await confirmDialog(
          context,
          title: 'Fix DNS safely',
          question: "Change this adapter's DNS to an independent resolver that returned the real address? NOBAD saves "
              'your current DNS first, checks other sites afterwards, and undoes the change automatically if anything breaks.',
          yes: 'Fix DNS safely',
        );
        if (!ok || !mounted) return;
        setState(() => _fix = null);
        await _call('ni_fix', {'id': jStr(inv['id'])}, 'fix');
      case 'rollback':
        final a = await scope.vpn.act(() async => Answer.fromJson(await scope.engine.call('ni_rollback', {'entry': extra['entry']})));
        if (a != null && !a.ok && a.data['detail'] is String) scope.vpn.toast(a.data['detail'] as String);
      case 'history':
        try {
          final a = Answer.fromJson(await scope.engine.call('ni_history'));
          if (a.ok && mounted) setState(() => _hist = a.data);
        } on Object {
          // offline: the shell says so
        }
      case 'hclear':
        final ok = await confirmDialog(context,
            title: 'Clear history', question: 'Delete the local diagnostic history and baselines?', yes: 'Clear', danger: true);
        if (!ok) return;
        await scope.vpn.act(() async => Answer.fromJson(await scope.engine.call('ni_history_clear')));
        await _go('history');
      case 'vpnconnect':
        if (!(scope.vpn.state?.connected ?? false)) await scope.vpn.toggle();
      case 'retarget':
        _site.text = jStr(extra['target']);
        await _go('investigate');
    }
  }

  Future<void> _setAuto(bool want) async {
    final scope = AppScope.of(context);
    setState(() => _autoPending = want);
    final a = await scope.vpn.act(() => scope.engine.setSetting('ni_autofix', want));
    if (!mounted) return;
    setState(() => _autoPending = null);
    if (a != null && a.ok) scope.vpn.toast(want ? 'Smart fix agent on' : 'Smart fix agent off', good: true);
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final vpn = AppScope.of(context).vpn;
    return ListenableBuilder(
      listenable: vpn,
      builder: (context, _) => SingleChildScrollView(
        padding: const EdgeInsets.all(NbSpace.x3),
        child: Align(
          alignment: Alignment.topLeft,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const PageTitle('Network Intelligence',
                    sub: 'Evidence-based diagnostics for your network, DNS, provider and VPN. Everything is measured live '
                        'on this PC; nothing is changed unless you ask, or switch on the fix agent.'),
                const SizedBox(height: NbSpace.x3),
                Semantics(
                  container: true,
                  label: 'Network Intelligence sections',
                  child: Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final (k, n) in _panes)
                      NbChipButton(n, on: _pane == k, onTap: () {
                        setState(() => _pane = k);
                        if (k == 'history') _go('history');
                      }),
                  ]),
                ),
                const SizedBox(height: NbSpace.x3),
                AnimatedSwitcher(
                  duration: NbMotion.of(context, NbMotion.base),
                  child: KeyedSubtree(key: ValueKey(_pane), child: _paneBody(c)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _paneBody(NbColors c) => switch (_pane) {
    'overview' => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _overview(c),
      const SizedBox(height: NbSpace.x3),
      _repairCard(c),
    ]),
    'sites' => _sites(c),
    'dns' => _dns(c),
    'ip' => _ip(c),
    'vpn' => _vpnPane(c),
    _ => _history(c),
  };

  Widget _busyLine(NbColors c, String key) => _busy.contains(key)
      ? Padding(
          padding: const EdgeInsets.only(top: NbSpace.x2),
          child: Semantics(
            liveRegion: true,
            child: Row(children: [
              SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.6, color: c.orange)),
              const SizedBox(width: 8),
              Flexible(child: Text(_busyWords[key] ?? 'Measuring…', style: NbType.text(NbSize.small, c.muted))),
            ]),
          ),
        )
      : const SizedBox.shrink();

  Widget _overview(NbColors c) {
    final o = _ov;
    final kids = <Widget>[
      _Head(
        title: 'Network overview',
        note: 'Adapters, gateway, DNS health, interception and changes since this network was last seen.',
        action: NbButton(o == null ? 'Analyze network' : 'Analyze again', small: true,
            onPressed: _busy.contains('overview') ? null : () => _go('overview')),
      ),
      _busyLine(c, 'overview'),
    ];
    if (o == null) {
      kids.add(const _Empty('Run an analysis to see your network.'));
    } else if (!jBool(o['ok'])) {
      kids.add(_issue('bad', jStr(o['error'], 'The analysis failed.')));
    } else {
      final s = jMap(o['snapshot']);
      final adapters = [for (final a in jList(s['adapters'])) jMap(a)];
      final p = adapters.where((a) => a['index'] == s['primary']).firstOrNull;
      final bl = jMap(o['baseline']);
      kids.add(Padding(
        padding: const EdgeInsets.only(top: NbSpace.x3),
        child: Wrap(spacing: NbSpace.x5, runSpacing: NbSpace.x2, children: [
          Metric('Uplink', p == null ? 'none' : jStr(p['name'])),
          Metric('IPv4 / IPv6', '${jBool(s['v4_available']) ? '✓' : '✕'} / ${jBool(s['v6_available']) ? '✓' : '✕'}'),
          Metric('This network', jBool(bl['known']) ? 'seen ${jInt(bl['seen'])}×' : 'new'),
        ]),
      ));
      if (p != null) {
        kids.addAll([
          _Kv('Gateway', _join(p['gateways4'])),
          _Kv('Windows DNS', _join([...jList(p['dns4']), ...jList(p['dns6'])])),
          _Kv("Network's own DNS (DHCP)", _join(p['dhcp_dns'])),
          _Kv('Encrypted DNS templates in Windows', '${jList(s['doh_templates']).length}'),
        ]);
      }
      kids.add(const _Sub('Resolvers'));
      for (final r in jList(o['resolvers']).map(jMap)) {
        kids.add(Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            _Tag(jStr(r['group'])),
            Text(jStr(r['ip']), style: NbType.data(NbSize.small, c.text)),
            Text(jBool(r['ok']) ? '${jNum(r['rtt_ms'])?.round() ?? '—'} ms' : jStr(r['error'], jStr(r['rcode'], 'no answer')),
                style: NbType.data(NbSize.small, jBool(r['ok']) ? c.sealed : c.blocked)),
            if (jBool(r['nx_hijack'])) Text('invents answers', style: NbType.text(NbSize.small, c.blocked)),
            if (jBool(r['in_use'])) const _Tag('in use'),
          ]),
        ));
      }
      kids.add(const _Sub('Findings'));
      final fs = jList(o['findings']);
      if (fs.isEmpty) {
        kids.add(_issue('good', 'Nothing unusual found',
            'DNS answers normally, nothing intercepts DNS, and nothing changed since this network was last seen.'));
      } else {
        kids.addAll(fs.map((f) => _Finding(jMap(f))));
      }
      kids.add(_foot(c, o));
    }
    return NbPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: kids));
  }

  /// Everything the command line can do (--panic, --repair-network quick|full), as buttons.
  Widget _repairCard(NbColors c) {
    final vpn = AppScope.of(context).vpn;
    final busy = vpn.busy.contains('net_repair');
    Widget row(String lvl, String title, String text, String label, NbButtonKind kind) => Padding(
      padding: const EdgeInsets.only(top: NbSpace.x3),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: NbType.label(NbSize.body, c.text)),
            Text(text, style: NbType.text(NbSize.small, c.muted, height: 1.45)),
          ]),
        ),
        const SizedBox(width: NbSpace.x3),
        NbButton(label, small: true, kind: kind, onPressed: busy ? null : () => netRepair(context, lvl)),
      ]),
    );
    return NbPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const _Head(
          title: 'Fix my internet',
          note: 'Works without internet. Start with the first option; each one asks before it changes anything and shows '
              'the real result of every step.',
        ),
        row('undo', '1 · Restore internet',
            "Removes NOBAD's firewall rules, tunnels and DNS changes. Use this if pages stopped loading after using NOBAD.",
            'Restore', NbButtonKind.primary),
        row('quick', '2 · Quick repair',
            'Also flushes DNS, clears the ARP cache and renews your IP address. Takes seconds; Wi-Fi may blink once.',
            'Repair', NbButtonKind.ghost),
        row('full', '3 · Full network reset',
            "Also resets Winsock, TCP/IP and proxy settings, like Windows' own network reset. Needs a restart; manually "
                'set IP addresses must be entered again.',
            'Reset…', NbButtonKind.danger),
        if (busy)
          Padding(padding: const EdgeInsets.only(top: NbSpace.x2), child: Text('Repairing network…', style: NbType.text(NbSize.small, c.muted))),
      ]),
    );
  }

  Widget _sites(NbColors c) {
    final st = AppScope.of(context).vpn.state;
    final auto = _autoPending ?? st?.setting('ni_autofix') ?? false;
    final kids = <Widget>[
      const _Head(
        title: 'Investigate a site',
        note: "Compares your network's DNS with independent and encrypted resolvers, then tests TCP, TLS and HTTP to find "
            'exactly where a site is blocked or failing.',
      ),
      const SizedBox(height: NbSpace.x2),
      Row(children: [
        Expanded(
          child: NbTextBox(controller: _site, label: '', hint: 'site.com or https://site.com/page', maxLength: 253,
              onSubmitted: (_) => _go('investigate')),
        ),
        const SizedBox(width: NbSpace.x2),
        NbButton('Investigate', onPressed: _busy.contains('investigate') ? null : () => _go('investigate')),
      ]),
      const SizedBox(height: NbSpace.x2),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        NbSwitch(value: auto, label: 'Smart fix agent', onChanged: _autoPending != null ? null : _setAuto),
        const SizedBox(width: NbSpace.x2),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Smart fix agent  ${auto ? 'On' : 'Off'}', style: NbType.label(NbSize.body, c.text)),
            Text(
              auto
                  ? 'On: fixes DNS filtering by itself, checks that nothing else broke, and undoes it automatically if something did.'
                  : 'Off: nothing is changed unless you click Fix.',
              style: NbType.text(NbSize.small, c.muted, height: 1.45),
            ),
          ]),
        ),
      ]),
      _busyLine(c, 'investigate'),
    ];
    final r = _inv;
    if (r == null) {
      kids.add(const _Empty("Enter a site that doesn't open (or any site) to see what your network does with it."));
    } else if (!jBool(r['ok'])) {
      kids.add(_issue('bad', jStr(r['error'], 'The investigation failed.')));
    } else {
      kids.add(_verdict(c, r));
      final fixable = jMap(r['fixable']);
      final recs = [for (final x in jList(r['recommendations'])) jMap(x)];
      for (final x in recs.where((x) => x['id'] != 'info')) {
        kids.add(Padding(
          padding: const EdgeInsets.only(top: NbSpace.x2),
          child: Row(children: [
            Expanded(child: Text(jStr(x['text']), style: NbType.text(NbSize.body, c.text, height: 1.45))),
            if (x['action'] == 'vpn') NbButton('Connect NOBAD', small: true, kind: NbButtonKind.ghost, onPressed: () => _go('vpnconnect')),
            if (x['action'] == 'dns_fix')
              NbButton('Fix DNS safely', small: true,
                  onPressed: (fixable.isNotEmpty && !jBool(fixable['ok'])) || _busy.contains('fix') ? null : () => _go('fix')),
          ]),
        ));
      }
      if (fixable.isNotEmpty && !jBool(fixable['ok']) && recs.any((x) => x['action'] == 'dns_fix')) {
        kids.add(Text('Fix not available: ${[for (final x in jList(fixable['reasons'])) '$x'].join('; ')}',
            style: NbType.text(NbSize.small, c.muted)));
      }
      kids.add(_fixBox(c));
      final moved = jList(r['findings']).map(jMap).where((f) => jStrN(f['moved_to']) != null).firstOrNull;
      if (moved != null) {
        kids.add(Padding(
          padding: const EdgeInsets.only(top: NbSpace.x2),
          child: Row(children: [
            Expanded(child: Text(jStr(moved['title']), style: NbType.text(NbSize.body, c.text))),
            NbButton('Investigate ${moved['moved_to']}', small: true, kind: NbButtonKind.ghost,
                onPressed: () => _go('retarget', {'target': moved['moved_to']})),
          ]),
        ));
      }
      kids.add(const _Sub('Evidence'));
      kids.addAll(jList(r['findings']).map((f) => _Finding(jMap(f))));
      final d = jMap(r['data']);
      kids.add(const _Sub('What each resolver answered'));
      for (final m in jList(d['matrix']).map(jMap)) {
        final a = jMap(jMap(m['results'])['A']), q = jMap(jMap(m['results'])['AAAA']);
        final who = jStrN(m['ip']) ?? (jStr(m['doh']).split('/').length > 2 ? jStr(m['doh']).split('/')[2] : '');
        final ans = a['rcode'] == 'NOERROR'
            ? [...jList(a['cnames']).map((x) => '→ $x'), _join(a['addrs'], empty: 'no address')].join(' ')
            : jStr(a['error'], jStr(a['rcode']));
        kids.add(_Row3(
          lead: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _Tag(jStr(m['group'])),
            Text(who, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.data(NbSize.small, c.text)),
          ]),
          body: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(ans, style: NbType.data(NbSize.small, c.text)),
            if (jList(q['addrs']).isNotEmpty) Text(_join(q['addrs']), style: NbType.data(NbSize.caption, c.muted)),
          ]),
          tail: jNum(a['rtt_ms']) == null ? '—' : '${jNum(a['rtt_ms'])!.round()} ms',
        ));
      }
      final isp = jMap(d['isp']);
      if (isp.isNotEmpty) {
        kids.add(const _Sub('Who is doing it'));
        kids.add(Text(
          jList(isp['matches']).isNotEmpty
              ? 'Evidence links the filtering to your provider: ${jStr(isp['provider_label'])}'
              : jStr(isp['note'], 'Not enough evidence to name the operator.'),
          style: NbType.text(NbSize.small, c.muted),
        ));
      }
      kids.add(_foot(c, r));
    }
    return NbPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: kids));
  }

  Widget _verdict(NbColors c, Map<String, Object?> r) {
    final st = statuses[r['status']] ??
        (r['verdict'] == 'name-does-not-exist' ? ("Name doesn't exist", 'warn', 'No such site: check the spelling.') : statuses['unknown']!);
    final tone = switch (st.$2) {
      'bad' => c.blocked,
      'good' => c.sealed,
      _ => c.amber,
    };
    final isp = jMap(jMap(r['data'])['isp']);
    final path = jStr(r['path']);
    var url = jStr(r['target']) + (path.isNotEmpty && path != '/' ? path : '');
    if (url.length > 64) url = '${url.substring(0, 61)}…';
    return Container(
      margin: const EdgeInsets.only(top: NbSpace.x3),
      padding: const EdgeInsets.all(NbSpace.x3),
      decoration: BoxDecoration(
        borderRadius: NbRadius.rowAll,
        border: Border.all(color: tone.withValues(alpha: .5)),
        color: tone.withValues(alpha: .06),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(color: tone.withValues(alpha: .15), borderRadius: NbRadius.pillAll),
            child: Text(st.$1, style: NbType.label(NbSize.small, tone)),
          ),
          const SizedBox(width: 8),
          Flexible(child: Text(url, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.data(NbSize.small, c.muted))),
        ]),
        const SizedBox(height: 6),
        Text(verdicts[r['verdict']] ?? jStr(r['verdict']), style: NbType.label(NbSize.title, c.text)),
        Text(st.$3, style: NbType.text(NbSize.small, c.muted, height: 1.45)),
        if (r['status'] == 'blocked' && jList(isp['matches']).isNotEmpty)
          Text('Done by: ${jStr(isp['provider_label'])}', style: NbType.label(NbSize.small, c.text)),
        if (r['affected'] == false && r['verdict'] == 'dns-filtering')
          Text("This PC isn't affected (Windows uses another resolver).", style: NbType.text(NbSize.small, c.muted))
        else if (r['affected'] == true)
          Text('Apps on this PC get the filtered answer.', style: NbType.text(NbSize.small, c.muted)),
        if (jList(r['steps']).isNotEmpty) ...[
          const SizedBox(height: 8),
          for (final x in jList(r['steps']).map(jMap))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(children: [
                SizedBox(
                  width: 16,
                  child: Text(x['state'] == 'ok' ? '✓' : (x['state'] == 'skip' ? '–' : '!'),
                      style: NbType.label(NbSize.small, x['state'] == 'ok' ? c.sealed : (x['state'] == 'skip' ? c.dim : c.blocked))),
                ),
                SizedBox(width: 140, child: Text(_steps[x['step']] ?? jStr(x['step']), style: NbType.text(NbSize.small, c.text))),
                Expanded(
                  child: Text(x['state'] == 'skip' ? 'not tested' : jStr(x['detail']),
                      style: NbType.text(NbSize.small, c.muted)),
                ),
              ]),
            ),
        ],
      ]),
    );
  }

  Widget _fixBox(NbColors c) {
    if (_busy.contains('fix')) {
      return Padding(
        padding: const EdgeInsets.only(top: NbSpace.x2),
        child: Text(
          _fixAuto
              ? 'Smart agent is fixing DNS, then checking other sites still work…'
              : 'Fixing DNS safely, then checking other sites still work…',
          style: NbType.text(NbSize.small, c.muted),
        ),
      );
    }
    final f = _fix;
    if (f == null) return const SizedBox.shrink();
    final ok = jBool(f['ok']);
    final servers = [for (final s in jList(f['servers'])) '$s'];
    final title = (_fixStates[f['state']] ?? jStr(f['state'])) +
        (servers.isEmpty ? '' : ' · ${servers.join(', ')} on ${jStr(f['adapter'])}');
    final detail = [
      for (final r in jList(f['reasons'])) '$r',
      for (final ch in jList(f['checks']).map(jMap)) '${jBool(ch['ok']) ? '✓' : '!'} ${jStr(ch['check'])} ${jStr(ch['detail'])}',
    ].join('\n');
    return Padding(
      padding: const EdgeInsets.only(top: NbSpace.x2),
      child: Notice(
        kind: ok ? NoticeKind.info : (f['state'] == 'refused' ? NoticeKind.warn : NoticeKind.bad),
        title: title,
        detail: detail,
        actions: [
          if (ok && jStrN(f['entry']) != null) NoticeAction('Undo this change', () => _go('rollback', {'entry': f['entry']})),
        ],
      ),
    );
  }

  static const _dnsTypes = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SOA'];

  Widget _dns(NbColors c) {
    final kids = <Widget>[
      const _Head(title: 'DNS intelligence', note: 'Ask every resolver for any record type and compare the raw answers.'),
      const SizedBox(height: NbSpace.x2),
      Row(children: [
        Expanded(child: NbTextBox(controller: _name, label: '', hint: 'example.com', maxLength: 253, onSubmitted: (_) => _go('lookup'))),
        const SizedBox(width: NbSpace.x2),
        NbButton('Look up', onPressed: _busy.contains('lookup') ? null : () => _go('lookup')),
      ]),
      const SizedBox(height: NbSpace.x2),
      Wrap(spacing: 6, runSpacing: 6, children: [
        for (final t in _dnsTypes)
          NbChipButton(t, on: _types.contains(t), onTap: () => setState(() => _types.contains(t) ? _types.remove(t) : _types.add(t))),
      ]),
      _busyLine(c, 'lookup'),
    ];
    final l = _lookup;
    if (l == null) {
      kids.add(const _Empty('Results appear here.'));
    } else {
      final types = [for (final t in jList(l['types'])) '$t'];
      for (final row in jList(l['rows']).map(jMap)) {
        kids.add(Padding(
          padding: const EdgeInsets.only(top: NbSpace.x3, bottom: 4),
          child: Row(children: [
            Text(jStr(row['label']), style: NbType.label(NbSize.body, c.text)),
            const SizedBox(width: 8),
            _Tag(jStr(row['group'])),
          ]),
        ));
        final recs = jMap(row['records']);
        for (final t in types) {
          final x = jMap(recs[t]);
          final String body;
          if (jStrN(x['error']) != null) {
            body = jStr(x['error']);
          } else if (jList(x['answers']).isNotEmpty) {
            body = [
              for (final a in jList(x['answers']).map(jMap)) '${jStr(a['type'])} ${a['data'] is String ? a['data'] : a['data'].toString()}  ttl ${a['ttl']}',
            ].join('\n');
          } else {
            final auth = jList(x['authority']);
            body = jStr(x['rcode']) + (auth.isNotEmpty ? ' · SOA ${jStr(jMap(jMap(auth.first)['data'])['mname'])}' : '');
          }
          kids.add(_Row3(
            lead: Text(t, style: NbType.label(NbSize.small, c.text)),
            body: Text(body, style: NbType.data(NbSize.small, jStrN(x['error']) != null ? c.blocked : c.text)),
            tail: jNum(x['rtt_ms']) == null ? '' : '${jNum(x['rtt_ms'])!.round()} ms',
          ));
        }
      }
    }
    return NbPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: kids));
  }

  Widget _ip(NbColors c) {
    final o = _ov;
    final kids = <Widget>[
      _Head(
        title: 'IPv4 / IPv6 analysis',
        note: 'Addresses, routes and DNS per adapter, from the last network analysis.',
        action: NbButton('Analyze', small: true, kind: NbButtonKind.ghost,
            onPressed: _busy.contains('overview') ? null : () => _go('overview')),
      ),
      _busyLine(c, 'overview'),
    ];
    if (o == null || !jBool(o['ok'])) {
      kids.add(const _Empty('Run a network analysis first.'));
    } else {
      final s = jMap(o['snapshot']);
      String addrs(Object? list, {bool v6 = false}) {
        final xs = [
          for (final x in jList(list).map(jMap))
            if (!v6 || x['kind'] != 'link-local') '${jStr(x['ip'])}${v6 ? '' : '/${x['prefix']}'} (${jStr(x['kind'])}, ${jStr(x['origin'])})',
        ];
        return xs.isEmpty ? (v6 ? 'link-local only' : '—') : xs.join(', ');
      }

      for (final a in jList(s['adapters']).map(jMap).where((a) => jStr(a['status']).toLowerCase() == 'up')) {
        kids.add(Container(
          margin: const EdgeInsets.only(top: NbSpace.x3),
          padding: const EdgeInsets.all(NbSpace.x3),
          decoration: BoxDecoration(color: c.card, borderRadius: NbRadius.rowAll, border: Border.all(color: c.line)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Text(jStr(a['name']), style: NbType.label(NbSize.body, c.text)),
              const SizedBox(width: 8),
              _Tag(jStr(a['role'])),
              if (a['index'] == s['primary']) ...[const SizedBox(width: 6), const _Tag('primary')],
            ]),
            Text('${jStr(a['description'])} · ${jStr(a['media'])} ${jStr(a['speed'])} · MTU ${a['mtu'] ?? '—'}',
                style: NbType.text(NbSize.small, c.muted)),
            _Kv('IPv4', addrs(a['ipv4'])),
            _Kv('IPv6', addrs(a['ipv6'], v6: true)),
            _Kv(
              'Default route',
              'v4 ${jBool(a['default4']) ? '✓ ${_join(a['gateways4'], empty: 'on-link')}' : '✕'} · '
                  'v6 ${jBool(a['default6']) ? '✓ ${_join(a['gateways6'], empty: 'on-link')}' : '✕'}',
            ),
            _Kv('DNS', _join([...jList(a['dns4']), ...jList(a['dns6'])])),
          ]),
        ));
      }
      kids.addAll(jList(o['findings']).map(jMap).where((f) => f['layer'] == 'ipv6' || f['layer'] == 'routing').map(_Finding.new));
    }
    return NbPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: kids));
  }

  Widget _vpnPane(NbColors c) {
    final connected = AppScope.of(context).vpn.state?.connected ?? false;
    final v = _vpn;
    final kids = <Widget>[
      _Head(
        title: 'VPN integrity',
        note: 'Checks that IPv4, IPv6 and DNS really go through the tunnel, and that nothing leaks around it.',
        action: NbButton('Check', small: true, onPressed: _busy.contains('vpn') ? null : () => _go('vpn')),
      ),
      _busyLine(c, 'vpn'),
    ];
    if (v == null) {
      kids.add(_Empty(connected ? 'Run the check while connected.' : 'Connect NOBAD, then run the check.'));
    } else if (!jBool(v['ok'])) {
      kids.add(_issue('bad', jStr(v['error'], 'The check failed.')));
    } else {
      if (jBool(v['connected'])) {
        kids.add(Padding(
          padding: const EdgeInsets.only(top: NbSpace.x3),
          child: Wrap(spacing: NbSpace.x5, runSpacing: NbSpace.x2, children: [
            Metric('Tunnel', jStr(v['tunnel'])),
            Metric('Kill switch', jBool(v['kill_switch']) ? '✓' : '✕'),
            Metric('DNS leak block', jBool(v['dns_block']) ? '✓' : '✕'),
          ]),
        ));
        for (final r in jList(v['routes']).map(jMap)) {
          kids.add(_Kv('${jStr(r['family'])} → ${jStr(r['dest'])}', jStr(r['via'], 'no route'),
              tone: jBool(r['tunnel']) ? c.sealed : c.blocked));
        }
        for (final t in jList(v['leak_tests']).map(jMap)) {
          kids.add(_Kv('Direct DNS to ${jStr(t['resolver'])}', jBool(t['answered']) ? 'answered (leak path)' : 'blocked',
              tone: jBool(t['answered']) ? c.blocked : c.sealed));
        }
      }
      kids.addAll(jList(v['findings']).map((f) => _Finding(jMap(f))));
      final tr = jList(v['transitions']);
      if (tr.isNotEmpty) {
        kids.add(const _Sub('Recent network transitions'));
        for (final t in tr.map(jMap)) {
          final ts = jNum(t['ts']);
          final when = ts == null ? '—' : TimeOfDay.fromDateTime(DateTime.fromMillisecondsSinceEpoch((ts * 1000).round())).format(context);
          kids.add(_Kv(when, '${jStr(t['kind'])} · ${jStr(t['detail'])}'));
        }
      }
    }
    return NbPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: kids));
  }

  Widget _history(NbColors c) {
    final h = _hist;
    final kids = <Widget>[
      _Head(
        title: 'Diagnostic history',
        note: 'Stored only on this PC. Networks are identified by a hash, never by name.',
        action: NbButton('Clear', small: true, kind: NbButtonKind.ghost, onPressed: () => _go('hclear')),
      ),
    ];
    if (h == null) {
      kids.add(const _Empty('Loading…'));
    } else {
      if (!jBool(h['enabled'])) {
        kids.add(Padding(
          padding: const EdgeInsets.only(top: NbSpace.x2),
          child: Text('History is off (Settings → Network Intelligence).', style: NbType.text(NbSize.small, c.muted)),
        ));
      }
      final items = jList(h['items']).map(jMap).toList();
      if (items.isEmpty) {
        kids.add(const _Empty('No diagnostics yet.'));
      } else {
        for (final x in items) {
          final ts = jNum(x['ts']);
          final when = ts == null ? '' : DateTime.fromMillisecondsSinceEpoch((ts * 1000).round()).toString().substring(0, 16);
          final findings = x['findings'] is List ? ([for (final f in jList(x['findings'])) '$f'].join(', ')) : null;
          final parts = [
            jStr(x['target']),
            if (jStrN(x['verdict']) != null) jStr(x['verdict']),
            if (jStrN(x['state']) != null) jStr(x['state']),
            if (findings != null) findings.isEmpty ? 'nothing unusual' : findings,
          ].where((s) => s.isNotEmpty).join(' · ');
          kids.add(_Row3(
            lead: Text(when, style: NbType.data(NbSize.caption, c.muted)),
            body: Text.rich(TextSpan(children: [
              TextSpan(text: '${jStr(x['kind'])}  ', style: NbType.label(NbSize.small, c.text)),
              TextSpan(text: parts, style: NbType.text(NbSize.small, c.muted)),
            ])),
            tail: '',
          ));
        }
      }
    }
    return NbPanel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: kids));
  }

  Widget _foot(NbColors c, Map<String, Object?> m) => Padding(
    padding: const EdgeInsets.only(top: NbSpace.x3),
    child: Text('Measured ${_ago(m['ts'])} ago · ${m['took_s'] ?? '—'} s', style: NbType.text(NbSize.caption, c.dim)),
  );

  static String _join(Object? list, {String empty = '—'}) {
    final xs = [for (final x in jList(list)) if (x != null && '$x'.isNotEmpty) '$x'];
    return xs.isEmpty ? empty : xs.join(', ');
  }

  Widget _issue(String sev, String title, [String detail = '']) => Padding(
    padding: const EdgeInsets.only(top: NbSpace.x2),
    child: Notice(kind: sev == 'bad' ? NoticeKind.bad : (sev == 'warn' ? NoticeKind.warn : NoticeKind.info), title: title, detail: detail),
  );
}

/// A finding: title, confidence, layer, evidence (and contradicting evidence), note, recommendations.
class _Finding extends StatelessWidget {
  const _Finding(this.f);
  final Map<String, Object?> f;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final sev = f['severity'];
    final tone = sev == 'bad' ? c.blocked : (sev == 'warn' ? c.amber : c.sealed);
    final conf = jNum(f['confidence']) ?? 0;
    return Container(
      margin: const EdgeInsets.only(top: NbSpace.x2),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        borderRadius: NbRadius.rowAll,
        color: c.card,
        border: Border(left: BorderSide(color: tone, width: 3)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Text(jStr(f['title']), style: NbType.label(NbSize.body, c.text))),
          if (sev != 'info')
            Tooltip(
              message: 'Confidence ${(conf * 100).round()}%',
              child: Text('${jStr(f['confidence_label'])} · ${(conf * 100).round()}%', style: NbType.data(NbSize.caption, c.muted)),
            ),
        ]),
        if (jStrN(f['layer']) != null) Padding(padding: const EdgeInsets.only(top: 4), child: _Tag(jStr(f['layer']))),
        for (final e in jList(f['evidence'])) _bullet(c, '$e', c.muted),
        for (final e in jList(f['contra'])) _bullet(c, '$e', c.dim),
        if (jStrN(f['note']) != null) Text(jStr(f['note']), style: NbType.text(NbSize.small, c.muted, height: 1.45)),
        for (final r in jList(f['recommend']))
          Padding(padding: const EdgeInsets.only(top: 4), child: Text('$r', style: NbType.text(NbSize.small, c.text, height: 1.45))),
      ]),
    );
  }

  Widget _bullet(NbColors c, String t, Color col) => Padding(
    padding: const EdgeInsets.only(top: 3),
    child: Text('•  $t', style: NbType.text(NbSize.small, col, height: 1.45)),
  );
}

class _Head extends StatelessWidget {
  const _Head({required this.title, required this.note, this.action});
  final String title;
  final String note;
  final Widget? action;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Semantics(header: true, child: Text(title, style: NbType.label(NbSize.lead, c.text))),
          const SizedBox(height: 4),
          Text(note, style: NbType.text(NbSize.small, c.muted, height: 1.45)),
        ]),
      ),
      if (action != null) ...[const SizedBox(width: NbSpace.x3), action!],
    ]);
  }
}

class _Sub extends StatelessWidget {
  const _Sub(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: NbSpace.x4, bottom: 2),
    child: Text(text, style: NbType.label(NbSize.body, NbColors.of(context).text)),
  );
}

class _Empty extends StatelessWidget {
  const _Empty(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      margin: const EdgeInsets.only(top: NbSpace.x3),
      padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 12),
      decoration: BoxDecoration(borderRadius: NbRadius.rowAll, border: Border.all(color: c.line2)),
      child: Text(text, textAlign: TextAlign.center, style: NbType.text(NbSize.body, c.muted, height: 1.45)),
    );
  }
}

class _Kv extends StatelessWidget {
  const _Kv(this.k, this.v, {this.tone});
  final String k;
  final String v;
  final Color? tone;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 6),
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.line))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 220, child: Text(k, style: NbType.text(NbSize.small, c.muted))),
        Expanded(child: SelectableText(v, style: NbType.data(NbSize.small, tone ?? c.text))),
      ]),
    );
  }
}

class _Row3 extends StatelessWidget {
  const _Row3({required this.lead, required this.body, required this.tail});
  final Widget lead;
  final Widget body;
  final String tail;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 6),
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.line))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 150, child: lead),
        const SizedBox(width: 8),
        Expanded(child: body),
        SizedBox(width: 56, child: Text(tail, textAlign: TextAlign.right, style: NbType.data(NbSize.caption, c.muted))),
      ]),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
      decoration: BoxDecoration(borderRadius: NbRadius.pillAll, border: Border.all(color: c.line2)),
      child: Text(text, style: NbType.text(NbSize.caption, c.muted)),
    );
  }
}
