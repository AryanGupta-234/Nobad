/// Settings: every setting of the WebView UI's GROUPS (nobadvpn/ui/app_ext.js), the same names and descriptions,
/// grouped the same way, with a search over names, descriptions and keywords. Each change goes to the engine as
/// `settings {key, value}`, where settings.coerce checks it as before.
library;

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../state/vpn_controller.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/motion.dart';
import '../../widgets/pressable.dart';
import '../../widgets/panels.dart';
import '../actions.dart';
import '../onboarding/setup.dart';

enum RowType { toggle, text, select, action, custom }

class SettingRow {
  const SettingRow(this.key, this.name, this.desc, {this.type = RowType.toggle, this.options = const [], this.hint,
      this.label, this.keywords = ''});
  const SettingRow.action(this.key, this.name, this.desc, this.label, {this.keywords = ''})
    : type = RowType.action, options = const [], hint = null;
  const SettingRow.custom(this.key) : name = '', desc = '', type = RowType.custom, options = const [], hint = null,
      label = null, keywords = '';
  final String key;
  final String name;
  final String desc;
  final RowType type;
  final List<(String, String)> options;
  final String? hint;
  final String? label;
  final String keywords;

  String get haystack => '$name $desc $keywords $key'.toLowerCase();
}

class SettingGroup {
  const SettingGroup(this.id, this.title, this.rows);
  final String id;
  final String title;
  final List<SettingRow> rows;
}

const services = [('', 'Off'), ('netflix', 'Netflix'), ('youtube', 'YouTube'), ('disney', 'Disney+'),
    ('prime', 'Prime Video'), ('spotify', 'Spotify'), ('twitch', 'Twitch')];

/// app_ext.js GROUPS, row for row.
const groups = [
  SettingGroup('protection', 'Protection', [
    SettingRow('kill_switch', 'Kill switch', 'Blocks any non-VPN traffic while connected and keeps blocking if the tunnel drops.', keywords: 'firewall leak block'),
    SettingRow('dns_leak_block', 'DNS leak block', 'While connected, DNS (ports 53 and 853) can only leave through the tunnel. Even a DNS server on your own router is blocked.', keywords: 'dns leak'),
    SettingRow('force_tunnel_dns', 'Add a fallback DNS when a config has none', "Adds a DNS line to the temporary runtime copy so the DNS block doesn't break name lookups. Your .conf files are never edited.", keywords: 'dns'),
    SettingRow('fallback_dns', 'Fallback DNS servers', 'Comma-separated IP addresses.', type: RowType.text, hint: '1.1.1.1, 1.0.0.1', keywords: 'dns'),
    SettingRow('ks_strict', 'Strict kill switch', 'Keep blocking even when a connection attempt fails. Use Restore internet to undo.', keywords: 'fail closed'),
    SettingRow('watchdog', 'Crash watchdog', 'A tiny helper restarts NOBAD if it crashes while the kill switch is armed.', keywords: 'crash restart'),
    SettingRow('watchdog_failopen', "Release the kill switch if NOBAD can't restart", 'Off keeps you blocked (safest). On restores internet after three failed restarts.', keywords: 'fail open'),
    SettingRow.action('panic', 'Restore internet now', 'Panic reset: removes every NOBAD firewall rule and stops NOBAD tunnels.', 'Panic reset', keywords: 'panic emergency reset'),
  ]),
  SettingGroup('safety', 'Network safety', [
    SettingRow('et_enabled', 'Evil Twin check on every network', 'When you join a network, NOBAD spends about 10 seconds checking for redirected DNS, a faked router (ARP spoofing), look-alike Wi-Fi, open Wi-Fi, HTTPS interception and proxies, then grades it A to F. Uses well-known public sites as references; nothing about you is sent.', keywords: 'evil twin public wifi hotspot arp spoof mitm grade trust'),
    SettingRow('et_vpn_below', 'Turn the VPN on below grade', 'Connects automatically when a network grades worse than this (not after you disconnected by hand).', type: RowType.select, options: [('off', 'Never'), ('A', 'A (anything less than perfect)'), ('B', 'B'), ('C', 'C (recommended)'), ('D', 'D (only clear attacks)')], keywords: 'evil twin auto connect grade'),
    SettingRow.custom('netsafety'),
    SettingRow.action('nr_quick', 'Quick network repair', 'Undoes every NOBAD change, then flushes DNS, clears the ARP cache and renews DHCP. Takes seconds; Wi-Fi may blink once.', 'Repair', keywords: 'fix internet dns broken reset network offline'),
    SettingRow.action('nr_full', 'Full network reset', 'Quick repair plus a Winsock, TCP/IP (IPv4 and IPv6) and WinHTTP proxy reset. Needs a restart, and manually set IP addresses must be entered again.', 'Reset…', keywords: 'winsock tcp ip reset broken offline'),
  ]),
  SettingGroup('netintel', 'Network Intelligence', [
    SettingRow('ni_autofix', 'Smart fix agent', "When a site is blocked by your network's DNS, switch this adapter's DNS to an independent resolver that returned the real address, verify that nothing else broke, and undo it automatically if something did. Also undone when you leave that network, and by any reset. Off: nothing changes unless you click Fix.", keywords: 'autofix blocked site dns agent'),
    SettingRow('ni_history', 'Keep local diagnostic history', 'Remembers what is normal for each network to spot changes. Stored only on this PC.', keywords: 'baseline history'),
    SettingRow('ni_reference_dns', 'Independent resolvers to compare with', 'Comma-separated IP addresses. At least two, so answers can be cross-checked.', type: RowType.text, hint: '1.1.1.1, 8.8.8.8, 9.9.9.9', keywords: 'dns compare reference'),
  ]),
  SettingGroup('connection', 'Connection', [
    SettingRow('auto_repair', 'Auto-repair & failover', 'Reconnects if the link degrades, then moves to a better server.', keywords: 'reconnect'),
    SettingRow('reconnect_on_network_change', 'Reconnect after sleep or network changes', 'Cleanly reconnects after the laptop wakes up or you switch between Wi-Fi and Ethernet. The kill switch stays armed meanwhile.', keywords: 'sleep resume wifi ethernet'),
    SettingRow('stream_tuned', 'Streaming-tuned tunnel', 'MTU 1380 and keepalive 25 on a temporary copy. Your .conf files stay untouched.', keywords: 'mtu keepalive'),
    SettingRow('auto_connect', 'Connect on launch', 'Reconnects to the last server when NOBAD starts.'),
    SettingRow('smart_select', 'Smart server choice', 'Learns which server is fastest at each time of day and uses that when failing over.', keywords: 'learn'),
    SettingRow('guard_service', 'Watch a streaming service', 'NOBAD checks this service through the tunnel and remembers which servers it works on.', type: RowType.select, options: services, keywords: 'netflix streaming blocked'),
    SettingRow('guard_auto_switch', 'Switch server if it gets blocked', 'If the watched service stops working, move to a server that still works.', keywords: 'netflix'),
  ]),
  SettingGroup('networks', 'Trusted networks', [
    SettingRow('ssid_rules', 'Use trusted-network rules', "Connect automatically on networks you don't trust, disconnect on ones you do.", keywords: 'wifi ssid home'),
    SettingRow('autoconnect_untrusted', 'Auto-connect on untrusted networks', 'Applies when rules are on.'),
    SettingRow('autodisconnect_trusted', 'Auto-disconnect on trusted networks', 'Applies when rules are on.'),
    SettingRow.custom('trusted'),
  ]),
  SettingGroup('startup', 'Startup & tray', [
    SettingRow('start_with_windows', 'Start with Windows', 'Runs at sign-in as an elevated scheduled task, so there is no UAC prompt each time.', keywords: 'autostart boot login'),
    SettingRow('tray', 'Tray icon', 'Quick connect, status and a compact window from the notification area.', keywords: 'system tray'),
    SettingRow('close_to_tray', 'Closing the window keeps NOBAD in the tray', 'Requires the tray icon.', keywords: 'minimize'),
    SettingRow('guardian', 'Keep guarding after the window closes', 'Stays in the background so auto-repair and the kill switch keep working.'),
    SettingRow('notifications', 'Windows notifications', 'Toasts for connect, drop, failover and kill-switch events.', keywords: 'toast alerts'),
    SettingRow('ui_flutter', 'Try the new NOBAD VPN 2.0 window (preview)', 'Uses the new window, which runs without administrator rights, from the next start. Turn it off to come back to this one.', keywords: 'flutter new window preview 2.0'),
    SettingRow('visual_effects', 'Visual effects', 'Frosted glass and ambient animations. Off keeps NOBAD light on CPU, GPU and battery.', keywords: 'performance animation blur battery lag'),
  ]),
  SettingGroup('connectivity', 'Connectivity', [
    SettingRow('net_adapt', 'Adapt to network blocks automatically', "If this network blocks a service NOBAD uses (by its name or through DNS), NOBAD switches to the service's official alternative name or looks it up with encrypted DNS, and remembers what works. Doesn't change Windows settings or your VPN traffic.", keywords: 'isp block dns doh alternative adapt auto'),
    SettingRow.action('reach_test', 'Test connectivity', 'Checks every service NOBAD uses on this network and shows which route works.', 'Test', keywords: 'reachability blocked isp check'),
    SettingRow.action('reach_forget', 'Re-learn routes', 'Forget the routes NOBAD remembered (done automatically when you change networks).', 'Reset', keywords: 'reset routes'),
  ]),
  SettingGroup('privacy', 'Privacy & security', [
    SettingRow('ip_lookup', 'Look up my exit IP address', 'Sends your public IP to third-party services (ipinfo.io and fallbacks) to show where you appear to be. Off means no lookup at all.', keywords: 'ipinfo third party'),
    SettingRow('startup_checks', 'Run extra checks at startup', 'Also runs the speed test, streaming service checks and VALORANT region checks each time NOBAD starts. These contact third-party sites. A quick connectivity check always runs.', keywords: 'speed test valorant'),
    SettingRow('encrypt_configs', 'Encrypt stored configs (Windows DPAPI)', 'Stores .conf files encrypted. This protects copies, backups and a stolen disk, not other administrators on this PC.', keywords: 'dpapi keys'),
    SettingRow('crash_reporting', 'Send crash reports (opt-in)', "Off by default. Reports are always saved locally; they're only sent if this is on and a server URL is set.", keywords: 'telemetry'),
    SettingRow('crash_report_url', 'Crash report server', 'HTTPS URL that receives reports.', type: RowType.text, hint: 'https://', keywords: 'telemetry'),
    SettingRow.custom('crash'),
    SettingRow.action('report', 'Report a problem', 'Saves a diagnostics zip (private keys removed) and opens a pre-filled bug report on GitHub in your browser. You attach the zip and submit; nothing is sent by NOBAD itself.', 'Report…', keywords: 'bug issue crash support help feedback github'),
    SettingRow.action('diag', 'Export diagnostics', 'Bundles logs, crash reports, settings and network checks into a zip with private keys removed.', 'Export…', keywords: 'logs support'),
  ]),
  SettingGroup('updates', 'Updates', [
    SettingRow('auto_install_wg', 'Reinstall WireGuard automatically', 'If WireGuard for Windows goes missing, NOBAD installs the official, signature-checked copy at start-up (works offline).', keywords: 'wireguard install repair'),
    SettingRow('auto_update_check', 'Check for updates on launch', 'Needs an update URL below.'),
    SettingRow('update_url', 'Update manifest URL', 'HTTPS link to the JSON manifest published with each release.', type: RowType.text, hint: 'https://', keywords: 'release'),
    SettingRow.custom('updates'),
  ]),
  SettingGroup('help', 'Help', [
    SettingRow.action('wizard', 'Setup checklist', 'Re-run the first-run checks and fixes.', 'Open setup', keywords: 'wizard onboarding'),
    SettingRow.custom('credits'),
  ]),
];

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _q = TextEditingController();
  String _cat = 'protection';
  List<Map<String, Object?>>? _changes;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        final a = Answer.fromJson(await AppScope.of(context).engine.call('net_changes'));
        if (mounted) setState(() => _changes = [for (final c in jList(a.data['changes'])) jMap(c)]);
      } on Object {
        // offline
      }
    });
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final vpn = AppScope.of(context).vpn;
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: vpn,
      builder: (context, _) {
        final s = vpn.state;
        if (s == null) return const SizedBox.shrink();
        final toks = _q.text.trim().toLowerCase().split(RegExp(r'\s+')).where((t) => t.isNotEmpty).toList();
        final shown = <(SettingGroup, List<SettingRow>)>[];
        for (final g in groups) {
          final rows = [
            for (final r in g.rows)
              if (toks.every((t) => '${r.haystack} ${g.title.toLowerCase()} ${r.type == RowType.custom ? r.key : ''}'.contains(t))) r,
          ];
          if (rows.isNotEmpty) shown.add((g, rows));
        }
        final searching = toks.isNotEmpty;
        final Widget content;
        if (searching) {
          content = shown.isEmpty
              ? Text('No settings match your search.', style: NbType.text(NbSize.body, c.muted))
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (final (g, rows) in shown)
                      Padding(
                        padding: const EdgeInsets.only(bottom: NbSpace.x3),
                        child: _GroupPanel(group: g, rows: rows, state: s, vpn: vpn, changes: _changes),
                      ),
                  ],
                );
        } else if (_cat == 'appearance') {
          content = _Appearance(state: s, vpn: vpn);
        } else if (_cat == 'log') {
          content = _LogPanel(vpn: vpn);
        } else {
          final g = groups.firstWhere((g) => g.id == _cat, orElse: () => groups.first);
          content = _GroupPanel(group: g, rows: g.rows, state: s, vpn: vpn, changes: _changes);
        }
        return Padding(
          padding: const EdgeInsets.all(NbSpace.x3),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 216,
                child: Glass(
                  level: GlassLevel.panel,
                  padding: const EdgeInsets.all(NbSpace.x2),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(6, 6, 6, 10),
                        child: Text('SETTINGS', style: NbType.display(NbSize.page - 2, c.text)),
                      ),
                      NbTextBox(controller: _q, label: '', hint: 'Search settings…', onChanged: (_) => setState(() {})),
                      const SizedBox(height: NbSpace.x2),
                      SizedBox(
                        height: categories.length * 32.0,
                        child: Stack(
                          children: [
                            if (!searching)
                              AnimatedPositioned(
                                duration: NbMotion.of(context, NbMotion.slow),
                                curve: const SpringCurve(damping: .8, stiffness: 240),
                                top: categories.indexWhere((x) => x.$1 == _cat) * 32.0,
                                left: 0,
                                right: 0,
                                height: 32,
                                child: DecoratedBox(
                                  decoration: BoxDecoration(color: c.raised, borderRadius: NbRadius.controlAll),
                                  child: Align(
                                    alignment: Alignment.centerLeft,
                                    child: Container(
                                      width: 3,
                                      height: 16,
                                      decoration: BoxDecoration(color: c.orange, borderRadius: NbRadius.pillAll),
                                    ),
                                  ),
                                ),
                              ),
                            for (var k = 0; k < categories.length; k++)
                              Positioned(
                                top: k * 32.0,
                                left: 0,
                                right: 0,
                                height: 32,
                                child: _CatRow(
                                  title: categories[k].$2,
                                  glyph: categories[k].$3,
                                  on: !searching && _cat == categories[k].$1,
                                  onTap: () => setState(() {
                                    _cat = categories[k].$1;
                                    _q.clear();
                                  }),
                                ),
                              ),
                          ],
                        ),
                      ),
                      const SizedBox(height: NbSpace.x2),
                      Container(height: 1, color: c.line),
                      const SizedBox(height: NbSpace.x2),
                      NbButton('Quit (VPN stays on)', small: true, kind: NbButtonKind.quiet, icon: NbGlyph.power,
                          onPressed: () => vpn.act(vpn.engine.quit)),
                      NbButton('Disconnect & quit', small: true, kind: NbButtonKind.quiet,
                          onPressed: () => vpn.act(() => vpn.engine.quit(disconnect: true))),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: NbSpace.x3),
              Flexible(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 640),
                  child: SingleChildScrollView(
                    child: AnimatedSwitcher(
                      duration: NbMotion.of(context, NbMotion.slow),
                      switchInCurve: NbMotion.curve,
                      transitionBuilder: (child, a) => FadeTransition(
                        opacity: a,
                        child: SlideTransition(
                          position: Tween(begin: const Offset(0, .015), end: Offset.zero).animate(a),
                          child: child,
                        ),
                      ),
                      layoutBuilder: (current, previous) =>
                          Stack(alignment: Alignment.topLeft, children: [...previous, ?current]),
                      child: KeyedSubtree(key: ValueKey(searching ? 'search' : _cat), child: content),
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

/// The sidebar: every settings category with its icon (the WebView's groups, plus Appearance and Log).
const categories = [
  ('protection', 'Protection', NbGlyph.shield),
  ('safety', 'Network safety', NbGlyph.lifebuoy),
  ('netintel', 'Network Intelligence', NbGlyph.rings),
  ('connection', 'Connection', NbGlyph.link),
  ('networks', 'Trusted networks', NbGlyph.wifi),
  ('startup', 'Startup & tray', NbGlyph.power),
  ('connectivity', 'Connectivity', NbGlyph.globe),
  ('privacy', 'Privacy & security', NbGlyph.lock),
  ('updates', 'Updates', NbGlyph.refresh),
  ('appearance', 'Appearance', NbGlyph.palette),
  ('log', 'Log', NbGlyph.list),
  ('help', 'Help', NbGlyph.help),
];

class _CatRow extends StatelessWidget {
  const _CatRow({required this.title, required this.glyph, required this.on, required this.onTap});
  final String title;
  final NbGlyph glyph;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Pressable(
      onTap: onTap,
      selected: on,
      semanticLabel: title,
      builder: (context, s) => AnimatedContainer(
        duration: NbMotion.of(context, NbMotion.fast),
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          color: !on && s.lit ? c.raised : null,
          borderRadius: NbRadius.controlAll,
        ),
        child: Row(
          children: [
            NbIcon(glyph, size: 16, color: on ? c.orange : c.muted),
            const SizedBox(width: 10),
            Expanded(
              child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: NbType.text(NbSize.body, on ? c.text : c.muted, weight: on ? FontWeight.w600 : FontWeight.w400)),
            ),
          ],
        ),
      ),
    );
  }
}

class _GroupPanel extends StatelessWidget {
  const _GroupPanel({required this.group, required this.rows, required this.state, required this.vpn, this.changes});
  final SettingGroup group;
  final List<SettingRow> rows;
  final VpnState state;
  final VpnController vpn;
  final List<Map<String, Object?>>? changes;

  void _act(BuildContext context, String a) {
    switch (a) {
      case 'panic':
        panic(context);
      case 'wizard':
        showSetup(context);
      case 'diag':
        vpn.act(vpn.engine.diagnosticsExport, done: 'Collecting diagnostics…');
      case 'report':
        vpn.act(vpn.engine.reportProblem, done: 'Preparing your report…');
      case 'reach_test':
        vpn.act(vpn.engine.reachTest, busyKey: 'reach');
      case 'reach_forget':
        vpn.act(vpn.engine.reachForget, done: 'Routes will be re-learned.');
      case 'nr_quick':
        netRepair(context, 'quick');
      case 'nr_full':
        netRepair(context, 'full');
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Semantics(
      container: true,
      label: group.title,
      child: NbPanel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(header: true, child: Text(group.title, style: NbType.text(NbSize.lead, c.text, weight: FontWeight.w600))),
            const SizedBox(height: NbSpace.x2),
            for (var i = 0; i < rows.length; i++) ...[
              if (i > 0) Container(height: 1, color: c.line),
              Padding(padding: const EdgeInsets.symmetric(vertical: 10), child: _row(context, rows[i])),
            ],
          ],
        ),
      ),
    );
  }

  Widget _row(BuildContext context, SettingRow r) {
    final c = NbColors.of(context);
    if (r.type == RowType.custom) return _custom(context, r.key);
    final disabled = (r.key == 'tray' || r.key == 'close_to_tray') && !state.tray;
    final Widget control = switch (r.type) {
      RowType.toggle => NbSwitch(
        value: state.setting(r.key),
        label: r.name,
        onChanged: disabled ? null : (v) => vpn.act(() => vpn.engine.setSetting(r.key, v)),
      ),
      RowType.text => NbField(
        key: ValueKey('${r.key}:${state.settingText(r.key)}'),
        value: state.settingText(r.key),
        label: r.name,
        width: 220,
        onSubmit: (v) => vpn.act(() => vpn.engine.setSetting(r.key, v)),
      ),
      RowType.select => NbSelect(
        value: r.options.any((o) => o.$1 == state.settingText(r.key)) ? state.settingText(r.key) : r.options.first.$1,
        options: r.options,
        label: r.name,
        maxWidth: 240,
        onChanged: (v) => vpn.act(() => vpn.engine.setSetting(r.key, v)),
      ),
      RowType.action => NbButton(
        r.key == 'reach_test' && vpn.busy.contains('reach') ? 'Testing…' : r.label!,
        small: true,
        kind: r.key == 'panic' || r.key == 'nr_full' ? NbButtonKind.danger : NbButtonKind.ghost,
        onPressed: r.key == 'reach_test' && vpn.busy.contains('reach') ? null : () => _act(context, r.key),
      ),
      RowType.custom => const SizedBox.shrink(),
    };
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(r.name, style: NbType.text(NbSize.body, c.text, weight: FontWeight.w600, height: 1.35)),
              const SizedBox(height: 3),
              Text(r.desc, style: NbType.text(NbSize.small, c.muted, height: 1.45)),
            ],
          ),
        ),
        const SizedBox(width: NbSpace.x4),
        control,
      ],
    );
  }

  Widget _custom(BuildContext context, String key) {
    final c = NbColors.of(context);
    final note = NbType.text(NbSize.small, c.muted, height: 1.45);
    switch (key) {
      case 'netsafety':
        final ch = changes ?? const [];
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Works even when NOBAD is closed or you are offline: Start menu → NOBAD VPN → Restore internet. If '
                'Windows restarts after NOBAD was killed with the kill switch on, a boot guard restores your internet '
                'by itself.', style: note),
            const SizedBox(height: 6),
            Text(ch.isEmpty
                ? 'NOBAD has not changed any Windows network setting outside its own tunnel and firewall rules.'
                : 'Windows settings NOBAD changed (each is undone by any reset):', style: note),
            for (final e in ch) Text('•  ${jStr(e['reason'], jStr(e['kind']))}', style: note),
            if (vpn.lastRepair.isNotEmpty)
              Text('Last repair: ${jStr(vpn.lastRepair['level'])} · '
                  '${jList(vpn.lastRepair['steps']).where((x) => jMap(x)['ok'] == true).length}/'
                  '${jList(vpn.lastRepair['steps']).length} steps succeeded'
                  '${jBool(vpn.lastRepair['restart_needed']) ? ' · restart Windows to finish' : ''}', style: note),
            if (vpn.busy.contains('net_repair')) Text('Repairing…', style: note),
          ],
        );
      case 'trusted':
        return _Trusted(state: state, vpn: vpn);
      case 'updates':
        final u = state.update ?? const Update();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Installed version: ${u.current}${u.checked ? ' · Latest: ${u.version.isEmpty ? u.current : u.version}' : ''}',
                style: note),
            if (u.error.isNotEmpty) Text(u.error, style: NbType.text(13, c.amber)),
            if (u.busy) Text('Downloading… ${u.progress}%', style: note),
            const SizedBox(height: 8),
            Wrap(spacing: 8, children: [
              NbButton('Check now', small: true, kind: NbButtonKind.ghost,
                  onPressed: u.configured ? () => vpn.act(vpn.engine.updateCheck) : null),
              if (u.available)
                NbButton('Install ${u.version}', small: true, onPressed: u.busy ? null : () => vpn.act(vpn.engine.updateInstall)),
            ]),
          ],
        );
      case 'credits':
        return Text('Server locations on the map: IP Geolocation by DB-IP (db-ip.com), CC BY 4.0, bundled with the app; '
            'nothing is looked up online unless "Look up my exit IP address" is on. Day and night are computed on this PC.',
            style: note);
      case 'crash':
        final n = state.crashPending;
        if (n == 0) return const SizedBox.shrink();
        return Row(children: [
          Expanded(child: Text('$n saved crash report(s)', style: note)),
          NbButton('Report it', small: true, kind: NbButtonKind.ghost,
              onPressed: () => vpn.act(() => vpn.engine.reportProblem(crash: true), done: 'Preparing your report…')),
        ]);
    }
    return const SizedBox.shrink();
  }
}

class _Trusted extends StatefulWidget {
  const _Trusted({required this.state, required this.vpn});
  final VpnState state;
  final VpnController vpn;
  @override
  State<_Trusted> createState() => _TrustedState();
}

class _TrustedState extends State<_Trusted> {
  final _add = TextEditingController();

  @override
  void dispose() {
    _add.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final s = widget.state, vpn = widget.vpn;
    final list = s.trustedNetworks;
    final fps = s.trustedFingerprints;
    final cur = s.networkName;
    final pend = s.pendingNetwork;
    final note = NbType.text(NbSize.small, c.muted, height: 1.45);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (pend.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Notice(
              kind: NoticeKind.warn,
              title: '"${jStr(pend['name'])}" doesn\'t match the network you trusted',
              detail: '${jStr(pend['why'])}. NOBAD treats it as untrusted until you confirm it. Only confirm if '
                  "you're sure this is your network.",
              actions: [NoticeAction('Confirm this network', () => vpn.act(() => vpn.engine.trustedAdd(jStr(pend['name']))))],
            ),
          ),
        Text('Current network: ${cur ?? 'none detected'}', style: note),
        const SizedBox(height: 8),
        if (list.isEmpty) Text('No trusted networks yet.', style: note),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final n in list)
              NbChipButton(
                fps.containsKey(n) ? '$n  ✕' : '$n (not confirmed)  ✕',
                tooltip: 'Remove $n',
                onTap: () => vpn.act(() => vpn.engine.setSetting('trusted_networks', [for (final x in list) if (x != n) x])),
              ),
          ],
        ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.end,
          children: [
            SizedBox(width: 220, child: NbTextBox(controller: _add, label: 'Network name', hint: 'Wi-Fi name, or Ethernet', maxLength: 64)),
            NbButton('Add', small: true, kind: NbButtonKind.ghost, onPressed: () async {
              final a = await vpn.act(() => vpn.engine.trustedAdd(_add.text.trim()));
              if (a != null && a.ok) _add.clear();
            }),
            if (cur != null)
              NbButton('Trust current network', small: true, kind: NbButtonKind.ghost,
                  onPressed: () => vpn.act(() => vpn.engine.trustedAdd(cur))),
          ],
        ),
      ],
    );
  }
}

class _Appearance extends StatelessWidget {
  const _Appearance({required this.state, required this.vpn});
  final VpnState state;
  final VpnController vpn;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return NbPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Appearance', style: NbType.text(NbSize.lead, c.text, weight: FontWeight.w600)),
          const SizedBox(height: 6),
          Text('One NOBAD identity. Choose the same orange-accented interface in light or dark mode.',
              style: NbType.text(13, c.muted, height: 1.5)),
          const SizedBox(height: 12),
          Wrap(spacing: 8, children: [
            NbChipButton('Dark mode', on: state.dark, onTap: () => vpn.act(() => vpn.engine.theme(true))),
            NbChipButton('Light mode', on: !state.dark, onTap: () => vpn.act(() => vpn.engine.theme(false))),
          ]),
        ],
      ),
    );
  }
}

/// The engine's recent log (the old footer), newest last, in Cascadia Mono.
class _LogPanel extends StatelessWidget {
  const _LogPanel({required this.vpn});
  final VpnController vpn;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final lines = vpn.logLines.reversed.take(40).toList();
    Color tone(String l) => switch (l) {
      'ok' => c.sealed,
      'warn' => c.amber,
      'bad' => c.blocked,
      _ => c.muted,
    };
    return NbPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Log', style: NbType.text(NbSize.lead, c.text, weight: FontWeight.w600)),
          const SizedBox(height: 8),
          if (lines.isEmpty) Text('Nothing yet.', style: NbType.text(13, c.muted)),
          SelectionArea(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final e in lines)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 3),
                    child: Text('${e.ts}  ${e.msg}', style: NbType.data(12, tone(e.level), height: 1.45)),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
