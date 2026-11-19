/// Home: compact panels over the live world map, like a desktop tool. The status panel says the protection state
/// in one display line (PROTECTED, CONNECTING, BLOCKED, NOT PROTECTED) with the aperture that changes it; the
/// servers sit on the right; throughput at the bottom. Nothing is stretched to fill space: what's left shows the
/// map, with your servers and the current connection drawn on it. With no servers yet, the free-server guide is
/// where the servers would be.
library;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../state/vpn_controller.dart';
import '../../widgets/aperture.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/panels.dart';
import '../../widgets/throughput_chart.dart';
import '../banners/banners.dart';
import '../onboarding/free_servers.dart';
import '../servers/server_row.dart';
import '../shell/shell.dart' show homeOf;
import '../../map/locate.dart';
import '../../map/map_view.dart';

/// The display line and the sentence under it, per state. Honest: "protected" only for a verified tunnel.
(String, String) headline(VpnState s) {
  final r = s.region(s.active ?? s.connecting);
  final where = r == null || r.place.isEmpty ? '' : ' in ${r.place}';
  return switch (s.protection) {
    Protection.protected => ('Protected', 'Your traffic leaves through ${s.active}$where.'),
    Protection.connecting => ('Connecting', 'Connecting to ${s.connecting}$where…'),
    Protection.blocked => ('Blocked', s.note ?? "Blocked by kill switch. You're not connected, so traffic outside the VPN is blocked."),
    Protection.off => (
      'Not protected',
      s.note ?? (s.regions.isEmpty ? 'Add a server to begin. NOBAD has none of its own.' : 'Choose a location to begin.'),
    ),
  };
}

Color toneOf(NbColors c, Protection p) => switch (p) {
  Protection.protected => c.sealed,
  Protection.connecting => c.amber,
  Protection.blocked => c.blocked,
  Protection.off => c.text,
};

/// The grid: one 12 px gutter everywhere. Left column (fixed width): status, notices, throughput. Right column:
/// the map (it takes what's left) over the servers. The two bottom panels share a height, so the edges line up.
const gutter = NbSpace.x3;
const leftColumn = 344.0;
const bottomRow = 224.0;
const headerHeight = 28.0;

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final vpn = scope.vpn;
    return ListenableBuilder(
      listenable: vpn,
      builder: (context, _) {
        final s = vpn.state;
        if (s == null) return const SizedBox.shrink();
        return Padding(
          padding: const EdgeInsets.all(gutter),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: leftColumn,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _StatusPanel(state: s, vpn: vpn),
                    const SizedBox(height: gutter),
                    const Expanded(child: SingleChildScrollView(child: Banners())),
                    const SizedBox(height: gutter),
                    SizedBox(height: bottomRow, child: _ThroughputPanel(vpn: vpn, connected: s.connected)),
                  ],
                ),
              ),
              const SizedBox(width: gutter),
              Expanded(
                // no servers yet: the free-server guide (the onboarding) takes the map's place
                child: s.regions.isEmpty
                    ? const _GuidePanel()
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Expanded(child: _MapPanel(state: s, vpn: vpn)),
                          const SizedBox(height: gutter),
                          SizedBox(height: bottomRow, child: _ServersPanel(state: s, vpn: vpn)),
                        ],
                      ),
              ),
            ],
          ),
        );
      },
    );
  }
}

/// The map in its own framed glass panel (Mica shows through the glass).
class _MapPanel extends StatelessWidget {
  const _MapPanel({required this.state, required this.vpn});
  final VpnState state;
  final VpnController vpn;

  @override
  Widget build(BuildContext context) {
    final s = state;
    final scope = AppScope.of(context);
    return Glass(
      level: GlassLevel.panel,
      child: MapView(
        servers: mapServers(s),
        home: homeOf(s, (scope.now ?? DateTime.now)()),
        selected: vpn.selected,
        status: mapStatus(s),
        connected: s.connected,
        now: scope.now,
        onSelect: vpn.select,
        onConnect: vpn.online ? (name) => vpn.connect(name) : null,
      ),
    );
  }
}

/// A panel's header: the title (14, semibold) and its actions, always 28 px tall.
class PanelHeader extends StatelessWidget {
  const PanelHeader(this.title, {super.key, this.count, this.actions = const []});
  final String title;
  final String? count;
  final List<Widget> actions;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return SizedBox(
      height: headerHeight,
      child: Row(
        children: [
          Text(title, style: NbType.label(NbSize.title, c.text)),
          if (count != null) ...[const SizedBox(width: 6), Text(count!, style: NbType.data(NbSize.small, c.dim))],
          const Spacer(),
          for (var i = 0; i < actions.length; i++) ...[if (i > 0) const SizedBox(width: 6), actions[i]],
        ],
      ),
    );
  }
}

class _StatusPanel extends StatelessWidget {
  const _StatusPanel({required this.state, required this.vpn});
  final VpnState state;
  final VpnController vpn;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final s = state;
    final (title, line) = headline(s);
    final tone = toneOf(c, s.protection);
    final verb = switch (s.protection) {
      Protection.protected => 'Disconnect',
      Protection.connecting => 'Cancel',
      _ => s.regions.isEmpty ? 'Add server' : 'Connect',
    };
    void press() {
      if (s.regions.isEmpty && !s.connected && s.connecting == null) {
        showFreeServers(context);
      } else {
        vpn.toggle();
      }
    }

    return Glass(
      level: GlassLevel.panel,
      padding: const EdgeInsets.all(gutter),
      rim: s.protection == Protection.off ? null : tone.withValues(alpha: .35),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            header: true,
            liveRegion: true,
            child: TweenAnimationBuilder<Color?>(
              tween: ColorTween(end: tone),
              duration: NbMotion.of(context, NbMotion.slow),
              curve: NbMotion.curve,
              builder: (context, col, _) => FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(title.toUpperCase(), maxLines: 1, style: NbType.display(NbSize.page, col ?? tone)),
              ),
            ),
          ),
          const SizedBox(height: 6),
          Text(line, style: NbType.text(NbSize.body, c.muted, height: 1.45)),
          const SizedBox(height: NbSpace.x4),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Aperture(
                protection: s.protection,
                label: verb,
                hint: s.regions.isEmpty
                    ? null
                    : (s.connected || s.connecting != null ? s.target : (s.region(vpn.selected) != null ? vpn.selected : s.target)),
                size: 112,
                onTap: vpn.online ? press : null,
              ),
              const SizedBox(width: NbSpace.x4),
              Expanded(child: _Facts(state: s, vpn: vpn)),
            ],
          ),
          const SizedBox(height: NbSpace.x3),
          _Toggles(state: s, vpn: vpn),
        ],
      ),
    );
  }
}

/// What is measured right now.
class _Facts extends StatelessWidget {
  const _Facts({required this.state, required this.vpn});
  final VpnState state;
  final VpnController vpn;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final s = state;
    final h = s.health;
    final exitIp = s.exitIp;
    final exitLine = s.exitLookupOff
        ? 'IP lookup is off in Settings'
        : (exitIp == null ? (s.connected ? 'Looking up…' : 'Exit address') : s.exitPlace);
    Widget mini(NbGlyph g, String label, VoidCallback f) => Tooltip(
      message: label,
      child: NbButton(label, kind: NbButtonKind.quiet, small: true, icon: g, onPressed: f),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        SelectableText(exitIp ?? '—', maxLines: 1, style: NbType.data(NbSize.lead, c.text, height: 1.25)),
        Text(exitLine, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.text(NbSize.small, c.dim)),
        Row(
          children: [
            if (exitIp != null)
              mini(NbGlyph.copy, 'Copy', () {
                Clipboard.setData(ClipboardData(text: exitIp));
                vpn.toast('Copied', good: true);
              }),
            mini(NbGlyph.refresh, 'Refresh', () => vpn.act(vpn.engine.ipinfo, busyKey: 'ipinfo')),
          ],
        ),
        const SizedBox(height: NbSpace.x2),
        Wrap(
          spacing: NbSpace.x4,
          runSpacing: NbSpace.x2,
          children: [
            EasedMetric('Latency', h?.rtt, format: (v) => '${v.round()} ms'),
            EasedMetric('Loss', h?.loss, format: (v) => '${v.round()} %'),
            Metric('Uptime', s.connected ? uptime(s.since, (AppScope.of(context).now ?? DateTime.now)()) : '—'),
          ],
        ),
      ],
    );
  }
}

/// The three protections you switch here (the old hero chips), and what is armed right now.
class _Toggles extends StatelessWidget {
  const _Toggles({required this.state, required this.vpn});
  final VpnState state;
  final VpnController vpn;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final s = state;
    Widget chip(String key, String label) {
      final on = s.setting(key);
      return NbChipButton(label, on: on, tooltip: on ? 'Turn $label off' : 'Turn $label on',
          onTap: () => vpn.act(() => vpn.engine.setSetting(key, !on)));
    }

    final armed = [if (s.ksActive) 'kill switch', if (s.dnsActive) 'DNS leak block'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(spacing: 6, runSpacing: 6, children: [
          chip('kill_switch', 'Kill switch'),
          chip('auto_repair', 'Auto-repair'),
          chip('stream_tuned', 'Stream tune'),
        ]),
        if (armed.isNotEmpty) ...[
          const SizedBox(height: 6),
          Row(children: [
            NbIcon(NbGlyph.shield, size: 14, color: c.sealed),
            const SizedBox(width: 6),
            Text('Armed: ${armed.join(' and ')}', style: NbType.text(NbSize.small, c.muted)),
          ]),
        ],
      ],
    );
  }
}

class _ThroughputPanel extends StatelessWidget {
  const _ThroughputPanel({required this.vpn, required this.connected});
  final VpnController vpn;
  final bool connected;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final t = vpn.traffic;
    return Glass(
      level: GlassLevel.panel,
      padding: const EdgeInsets.all(gutter),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PanelHeader('Throughput', actions: [
            _Rate('Down', connected ? t.rxBps : null, c.orange),
            const SizedBox(width: NbSpace.x2),
            _Rate('Up', connected ? t.txBps : null, c.muted),
          ]),
          const SizedBox(height: NbSpace.x2),
          Expanded(
            child: LayoutBuilder(
              builder: (context, box) => ThroughputChart(samples: vpn.samples, active: connected, height: box.maxHeight),
            ),
          ),
        ],
      ),
    );
  }
}

class _Rate extends StatelessWidget {
  const _Rate(this.label, this.value, this.swatch);
  final String label;
  final double? value;
  final Color swatch;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 8, height: 2, decoration: BoxDecoration(color: swatch, borderRadius: NbRadius.pillAll)),
        const SizedBox(width: 6),
        Text('$label ', style: NbType.text(NbSize.small, c.muted)),
        EasedNumber(value, format: rate, style: NbType.data(NbSize.small, c.text)),
      ],
    );
  }
}

/// Sorted for a glance: favourites first, then the fastest measured, then the rest by name.
List<Region> glanceOrder(VpnState s) {
  final fav = s.favorites.toSet();
  final list = [...s.regions];
  int score(Region r) => r.ping?.rtt == null ? 1 << 20 : r.ping!.rtt!.round();
  list.sort((a, b) {
    final fa = fav.contains(a.name) ? 0 : 1, fb = fav.contains(b.name) ? 0 : 1;
    if (fa != fb) return fa - fb;
    final d = score(a) - score(b);
    return d != 0 ? d : a.name.toLowerCase().compareTo(b.name.toLowerCase());
  });
  return list;
}

class _ServersPanel extends StatelessWidget {
  const _ServersPanel({required this.state, required this.vpn});
  final VpnState state;
  final VpnController vpn;

  @override
  Widget build(BuildContext context) {
    final s = state;
    final rows = glanceOrder(s);
    final busy = vpn.busy.contains('fastest');
    return Glass(
      level: GlassLevel.panel,
      padding: const EdgeInsets.all(gutter),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PanelHeader('Servers', count: '${s.regions.length}', actions: [
            Tooltip(
              message: 'Measure every server and connect to the best response. The tunnel drops for a moment; '
                  'the kill switch stays on.',
              child: NbButton(busy ? 'Measuring…' : 'Fastest', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.bolt,
                  onPressed: busy || !vpn.online ? null : () => vpn.act(vpn.engine.fastest, busyKey: 'fastest')),
            ),
            NbButton('Smart pick', small: true, kind: NbButtonKind.ghost,
                onPressed: busy || !vpn.online ? null : () => vpn.act(vpn.engine.smart, busyKey: 'fastest')),
            NbButton('Add', small: true, kind: NbButtonKind.quiet, icon: NbGlyph.gift, onPressed: () => showFreeServers(context)),
            NbButton('Manage', small: true, kind: NbButtonKind.quiet,
                onPressed: () => AppScope.of(context).nav.go(AppTab.servers)),
          ]),
          const SizedBox(height: NbSpace.x2),
          Expanded(
            child: SingleChildScrollView(
              child: SpringColumn(
                itemHeight: compactRowHeight + 4,
                children: [
                  for (final r in rows)
                    Padding(
                      key: ValueKey(r.name),
                      padding: const EdgeInsets.only(bottom: 4),
                      child: ServerRow(
                        region: r,
                        dense: true,
                        selected: vpn.selected == r.name,
                        located: locate(r) != null,
                        active: s.connected && s.active == r.name,
                        connecting: s.connecting == r.name,
                        favorite: s.favorites.contains(r.name),
                        onTap: () => vpn.select(vpn.selected == r.name ? null : r.name),
                        onConnect: vpn.online
                            ? () => (s.connected && s.active == r.name) || s.connecting == r.name
                                  ? vpn.act(vpn.engine.disconnect)
                                  : vpn.connect(r.name)
                            : null,
                        onStar: () => vpn.act(() => vpn.engine.favorite(r.name)),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// No servers yet: the free-server guide, where the servers would be.
class _GuidePanel extends StatelessWidget {
  const _GuidePanel();
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Glass(
      level: GlassLevel.panel,
      padding: const EdgeInsets.all(gutter),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Get free servers', style: NbType.label(NbSize.title, c.text)),
            const SizedBox(height: NbSpace.x2),
            DefaultTextStyle(style: NbType.text(NbSize.body, c.muted, height: 1.5), child: const FreeServersGuide()),
          ],
        ),
      ),
    );
  }
}
