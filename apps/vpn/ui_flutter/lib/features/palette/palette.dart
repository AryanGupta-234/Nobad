/// The command palette (Ctrl+K), Raycast-style: one box, everything NOBAD can do. Actions, screens, servers and every
/// setting, with the WebView palette's fuzzy matching (nobadvpn/ui/palette.js) and its words; free text becomes
/// "Investigate (site)" and "Where to watch (title)". Keyboard first: type, arrows, Enter, Esc. Recently used first.
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
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';
import '../actions.dart';
import '../onboarding/free_servers.dart';
import '../settings/settings_screen.dart';

class PaletteItem {
  const PaletteItem(this.id, this.group, this.title, this.run, {this.hint = '', this.keywords = '', this.always = false});
  final String id, group, title, hint, keywords;
  final VoidCallback run;

  /// Free-text actions ("Investigate …") always show while there's a query.
  final bool always;
}

/// Fuzzy score, as palette.js: substring > word-start initials > in-order letters; 0 = no match.
int paletteScore(String q, String text) {
  final s = q.toLowerCase().trim(), t = text.toLowerCase();
  if (s.isEmpty) return 1;
  final i = t.indexOf(s);
  if (i == 0) return 1000 - t.length;
  if (i > 0 && RegExp('[^a-z0-9]').hasMatch(t[i - 1])) return 800 - i;
  final words = t.split(RegExp('[^a-z0-9]+')).where((w) => w.isNotEmpty).toList();
  final initials = words.map((w) => w[0]).join();
  if (s.length >= 2 && !s.contains(' ') && initials.startsWith(s)) return 760 - words.length;
  if (s.split(RegExp(r'\s+')).every((part) => words.any((w) => w.startsWith(part)))) return 700;
  if (i > 0) return 420 - i;
  var j = 0, gaps = 0;
  for (final ch in t.split('')) {
    if (j < s.length && ch == s[j]) {
      j++;
    } else if (j > 0) {
      gaps++;
    }
    if (j == s.length) break;
  }
  return j == s.length ? (300 - gaps * 3).clamp(1, 300) : 0;
}

final _looksLikeHost = RegExp(r'^[a-z0-9-]+(\.[a-z0-9-]+)+(/.*)?$', caseSensitive: false);

/// Everything the palette offers right now, for query [q].
List<PaletteItem> paletteItems(BuildContext context, VpnController vpn, AppNav nav, String q) {
  final s = vpn.state ?? const VpnState();
  final e = vpn.engine;
  void go(AppTab t) => nav.go(t);
  final items = <PaletteItem>[
    PaletteItem('main', 'Actions', s.connected ? 'Disconnect' : 'Connect', vpn.toggle,
        hint: s.connected ? (s.active ?? '') : (vpn.selected ?? s.target ?? ''), keywords: 'vpn on off'),
    PaletteItem('fastest', 'Actions', 'Connect to the fastest server', () => vpn.act(e.fastest, busyKey: 'fastest'),
        keywords: 'quick best latency'),
    PaletteItem('ks', 'Actions', s.setting('kill_switch') ? 'Turn the kill switch off' : 'Turn the kill switch on',
        () => vpn.act(() => e.setSetting('kill_switch', !s.setting('kill_switch'))), keywords: 'kill switch block leak'),
    PaletteItem('speed', 'Actions', 'Run a speed test', () {
      go(AppTab.speed);
      vpn.act(() async => Answer.fromJson(await e.call('speedtest')));
    }, keywords: 'bandwidth mbps'),
    PaletteItem('stream', 'Actions', 'Check streaming services', () {
      go(AppTab.speed);
      vpn.act(() async => Answer.fromJson(await e.call('streamcheck')));
    }, keywords: 'netflix youtube disney prime reachability'),
    PaletteItem('netcheck', 'Actions', 'Run a network check', () {
      go(AppTab.network);
      vpn.act(() async => Answer.fromJson(await e.call('network_diagnose')));
    }, keywords: 'router internet dns health'),
    PaletteItem('probe', 'Actions', 'Probe all servers', () {
      go(AppTab.servers);
      vpn.act(e.probe, busyKey: 'probe');
    }, keywords: 'ping latency'),
    PaletteItem('restore', 'Actions', 'Restore internet', () => panic(context), keywords: 'panic reset fix offline firewall'),
    PaletteItem('repair', 'Actions', 'Quick network repair', () => netRepair(context, 'quick'),
        keywords: 'fix internet dns flush dhcp'),
    PaletteItem('theme', 'Actions', 'Switch light / dark mode', () => vpn.act(() => e.theme(!s.dark)), keywords: 'theme appearance'),
    PaletteItem('free', 'Actions', 'Free servers', () => showFreeServers(context), keywords: 'proton warp get servers onboarding'),
    PaletteItem('import', 'Actions', 'Import .conf', () => importFiles(context), keywords: 'wireguard add config file'),
    PaletteItem('url', 'Actions', 'Import from URL', () => importUrl(context), keywords: 'link https config'),
    PaletteItem('paste', 'Actions', 'Paste config', () => openEditor(context), keywords: 'text clipboard'),
    PaletteItem('mini', 'Actions', 'Open the quick view', () => vpn.act(() => e.uiShow('mini')), keywords: 'mini window tray compact'),
    PaletteItem('report', 'Actions', 'Report a problem', () => vpn.act(e.reportProblem, done: 'Preparing your report…'),
        keywords: 'bug issue crash support help feedback github'),
    PaletteItem('configs', 'Actions', 'Open the configs folder', () => vpn.act(e.openConfigs), keywords: 'wireguard conf files'),
    PaletteItem('watch', 'Actions', 'Where to watch…', () => go(AppTab.streaming), keywords: 'movie series anime streaming country'),
    for (final (t, name, kw) in const [
      (AppTab.home, 'Home', 'status map connect'),
      (AppTab.servers, 'Servers', 'locations configs probe'),
      (AppTab.speed, 'Speed', 'speed test services launch diagnostics'),
      (AppTab.network, 'Network', 'health gaming valorant ping evil twin'),
      (AppTab.intel, 'Intel', 'network intelligence dns investigate'),
      (AppTab.streaming, 'Streaming', 'where to watch titles countries'),
      (AppTab.activity, 'Activity', 'usage history sessions protection details log'),
      (AppTab.settings, 'Settings', 'preferences options'),
    ])
      PaletteItem('tab:${t.name}', 'Go to', name, () => go(t), keywords: kw),
    for (final r in s.regions)
      PaletteItem('srv:${r.name}', 'Servers', '${s.connected && s.active == r.name ? 'Connected: ' : 'Connect to '}${r.name}', () {
        vpn.select(r.name);
        vpn.connect(r.name);
      },
          hint: [if (r.ping?.rtt != null) '${r.ping!.rtt!.round()} ms', if (r.country.isNotEmpty) r.country].join(' · '),
          keywords: '${r.name} ${r.country} ${r.host}'),
    for (final g in groups)
      for (final row in g.rows)
        if (row.type == RowType.toggle)
          PaletteItem('set:${row.key}', 'Settings', '${row.name}: ${s.setting(row.key) ? 'turn off' : 'turn on'}',
              () => vpn.act(() => e.setSetting(row.key, !s.setting(row.key)),
                  done: '${row.name}: ${s.setting(row.key) ? 'off' : 'on'}'),
              hint: '${g.title} · ${s.setting(row.key) ? 'on' : 'off'}', keywords: '${row.keywords} ${row.desc}')
        else if (row.type != RowType.custom)
          PaletteItem('set:${row.key}', 'Settings', row.name, () => go(AppTab.settings),
              hint: g.title, keywords: '${row.keywords} ${row.desc} ${row.label ?? ''}'),
  ];
  final qq = q.trim();
  if (qq.length >= 2) {
    if (_looksLikeHost.hasMatch(qq.replaceFirst(RegExp(r'^https?://'), ''))) {
      items.add(PaletteItem('q:investigate', 'Ask', 'Investigate “$qq”', () => nav.goAsk(AppTab.intel, 'investigate', qq),
          hint: 'Network Intelligence', always: true));
    }
    items.add(PaletteItem('q:watch', 'Ask', 'Where to watch “$qq”', () => nav.goAsk(AppTab.streaming, 'watch', qq),
        hint: 'streaming catalogues by country', always: true));
  }
  return items;
}

/// Ranks [all] for [q] the palette.js way: recent first without a query; groups kept together; dedupe by title.
List<PaletteItem> rankPalette(List<PaletteItem> all, String q, List<String> recent) {
  final scored = <(PaletteItem, double)>[];
  for (final x in all) {
    final sc = x.always ? 1.0 : [paletteScore(q, x.title).toDouble(), paletteScore(q, x.keywords) * .6].reduce((a, b) => a > b ? a : b);
    if (sc > 0) {
      final r = recent.indexOf(x.id);
      scored.add((x, r >= 0 ? sc + (q.isEmpty ? 2000 - r * 10 : 40 - r * 4) : sc));
    }
  }
  final best = scored.where((o) => !o.$1.always).fold(0.0, (m, o) => o.$2 > m ? o.$2 : m);
  if (q.isNotEmpty && best >= 400) scored.removeWhere((o) => !o.$1.always && o.$2 < 300);
  List<PaletteItem> list;
  if (q.isEmpty) {
    final rec = scored.where((o) => recent.contains(o.$1.id)).toList()..sort((a, b) => b.$2.compareTo(a.$2));
    list = [
      for (final o in rec) PaletteItem(o.$1.id, 'Recent', o.$1.title, o.$1.run, hint: o.$1.hint),
      for (final o in scored)
        if (!recent.contains(o.$1.id) && (o.$1.group == 'Actions' || o.$1.group == 'Go to')) o.$1,
    ];
  } else {
    scored.sort((a, b) => b.$2.compareTo(a.$2));
    final top = scored.take(40).map((o) => o.$1).toList();
    final ask = top.where((x) => x.group == 'Ask').toList(), rest = top.where((x) => x.group != 'Ask').toList();
    final order = <String>[], by = <String, List<PaletteItem>>{};
    for (final x in rest) {
      if (!by.containsKey(x.group)) order.add(x.group);
      (by[x.group] ??= []).add(x);
    }
    final grouped = [for (final g in order) ...by[g]!];
    list = best >= 700 ? [...grouped, ...ask] : [...ask, ...grouped];
  }
  final seen = <String>{};
  return [for (final x in list) if (seen.add(x.title.toLowerCase())) x];
}

final _recent = <String>[];

Future<void> showPalette(BuildContext context) => showScoped<void>(context, (ctx) => const CommandPalette());

class CommandPalette extends StatefulWidget {
  const CommandPalette({super.key});
  @override
  State<CommandPalette> createState() => _CommandPaletteState();
}

class _CommandPaletteState extends State<CommandPalette> {
  final _q = TextEditingController();
  final _scroll = ScrollController();
  int _sel = 0;

  @override
  void dispose() {
    _q.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _run(PaletteItem x) {
    _recent
      ..remove(x.id)
      ..insert(0, x.id);
    while (_recent.length > 8) {
      _recent.removeLast();
    }
    Navigator.pop(context);
    x.run();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final scope = AppScope.of(context);
    final list = rankPalette(paletteItems(context, scope.vpn, scope.nav, _q.text), _q.text, _recent);
    if (_sel >= list.length) _sel = list.isEmpty ? 0 : list.length - 1;
    return Align(
      alignment: const Alignment(0, -.55),
      child: Material(
        type: MaterialType.transparency,
        child: SizedBox(
          width: 560,
          child: CallbackShortcuts(
            bindings: {
              const SingleActivator(LogicalKeyboardKey.arrowDown): () => setState(() => _sel = (_sel + 1).clamp(0, list.length - 1)),
              const SingleActivator(LogicalKeyboardKey.arrowUp): () => setState(() => _sel = (_sel - 1).clamp(0, list.length - 1)),
              const SingleActivator(LogicalKeyboardKey.enter): () {
                if (list.isNotEmpty) _run(list[_sel]);
              },
              const SingleActivator(LogicalKeyboardKey.escape): () => Navigator.pop(context),
            },
            child: Glass(
              level: GlassLevel.blur,
              radius: 12,
              fill: c.dialog,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(NbSpace.x3, NbSpace.x3, NbSpace.x3, NbSpace.x2),
                    child: Row(
                      children: [
                        NbIcon(NbGlyph.search, color: c.muted),
                        const SizedBox(width: NbSpace.x2),
                        Expanded(
                          child: Semantics(
                            label: 'Command or server',
                            child: TextField(
                              controller: _q,
                              autofocus: true,
                              onChanged: (_) => setState(() => _sel = 0),
                              style: NbType.text(NbSize.lead, c.text),
                              cursorColor: c.orange,
                              decoration: InputDecoration.collapsed(
                                hintText: 'Search actions, servers, settings… or type a site or a title',
                                hintStyle: NbType.text(NbSize.lead, c.dim),
                              ),
                            ),
                          ),
                        ),
                        Text('Esc', style: NbType.data(NbSize.caption, c.dim)),
                      ],
                    ),
                  ),
                  Container(height: 1, color: c.edge),
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 360),
                    child: list.isEmpty
                        ? Padding(
                            padding: const EdgeInsets.all(NbSpace.x4),
                            child: Text('No match. Try a server, a setting or an action.',
                                style: NbType.text(NbSize.body, c.muted)),
                          )
                        : ListView.builder(
                            controller: _scroll,
                            shrinkWrap: true,
                            padding: const EdgeInsets.all(NbSpace.x1),
                            itemCount: list.length,
                            itemBuilder: (context, i) {
                              final x = list[i];
                              final head = i == 0 || list[i - 1].group != x.group;
                              return Column(
                                crossAxisAlignment: CrossAxisAlignment.stretch,
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  if (head)
                                    Padding(
                                      padding: const EdgeInsets.fromLTRB(10, 8, 10, 4),
                                      child: Text(x.group, style: NbType.label(NbSize.caption, c.dim)),
                                    ),
                                  _Row(item: x, selected: i == _sel, onTap: () => _run(x), onHover: () => setState(() => _sel = i)),
                                ],
                              );
                            },
                          ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.item, required this.selected, required this.onTap, required this.onHover});
  final PaletteItem item;
  final bool selected;
  final VoidCallback onTap, onHover;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return MouseRegion(
      onEnter: (_) => onHover(),
      child: Pressable(
        onTap: onTap,
        selected: selected,
        semanticLabel: item.title,
        focusRing: false,
        builder: (context, s) => AnimatedContainer(
          duration: NbMotion.of(context, NbMotion.fast),
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(color: selected ? c.orangeA(.14) : null, borderRadius: NbRadius.controlAll),
          child: Row(
            children: [
              Expanded(
                child: Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: NbType.text(NbSize.body, selected ? c.text : c.muted, weight: selected ? FontWeight.w600 : FontWeight.w400)),
              ),
              if (item.hint.isNotEmpty) Text(item.hint, style: NbType.data(NbSize.caption, c.dim)),
            ],
          ),
        ),
      ),
    );
  }
}
