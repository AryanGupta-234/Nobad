/// Servers: every WireGuard config NOBAD has, to search, sort, star, edit, measure and add to.
library;

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';
import '../../widgets/panels.dart';
import '../actions.dart';
import '../onboarding/free_servers.dart';
import 'server_row.dart';

class ServersScreen extends StatefulWidget {
  const ServersScreen({super.key});
  @override
  State<ServersScreen> createState() => _ServersScreenState();
}

class _ServersScreenState extends State<ServersScreen> {
  final _q = TextEditingController();
  String _sort = 'best';
  bool _onlyFav = false;

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  List<Region> _rows(VpnState s) {
    final q = _q.text.trim().toLowerCase();
    final fav = s.favorites.toSet();
    final list = [
      for (final r in s.regions)
        if ((!_onlyFav || fav.contains(r.name)) &&
            (q.isEmpty || '${r.name} ${r.host} ${r.place}'.toLowerCase().contains(q)))
          r,
    ];
    int rtt(Region r) => r.ping?.rtt == null ? 1 << 20 : r.ping!.rtt!.round();
    int name(Region a, Region b) => a.name.toLowerCase().compareTo(b.name.toLowerCase());
    list.sort(switch (_sort) {
      'name' => name,
      'recent' => (a, b) {
        final d = (fav.contains(a.name) ? 0 : 1) - (fav.contains(b.name) ? 0 : 1);
        return d != 0 ? d : name(a, b);
      },
      _ => (a, b) {
        final d = rtt(a) - rtt(b);
        return d != 0 ? d : name(a, b);
      },
    });
    return list;
  }

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final vpn = scope.vpn;
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: vpn,
      builder: (context, _) {
        final s = vpn.state;
        if (s == null) return const SizedBox.shrink();
        final rows = _rows(s);
        return LayoutBuilder(
          builder: (context, box) {
            return SingleChildScrollView(
              padding: const EdgeInsets.all(NbSpace.x3),
              child: Align(
                alignment: Alignment.topLeft,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 720),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      PageTitle('Servers',
                          sub: s.regions.isEmpty
                              ? 'Manage and compare your WireGuard endpoints'
                              : '${s.regions.length} location(s). Manage and compare your WireGuard endpoints.'),
                      const SizedBox(height: NbSpace.x4),
                      Wrap(
                        spacing: NbSpace.x2,
                        runSpacing: NbSpace.x2,
                        children: [
                          NbButton('Free servers', small: true, icon: NbGlyph.gift, onPressed: () => showFreeServers(context)),
                          NbButton('Import .conf', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.folder,
                              onPressed: () => importFiles(context)),
                          NbButton('Import from URL', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.link,
                              onPressed: () => importUrl(context)),
                          NbButton('Paste config', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.plus,
                              onPressed: () => openEditor(context)),
                          NbButton(vpn.busy.contains('probe') ? 'Probing…' : 'Probe all', small: true, kind: NbButtonKind.ghost,
                              icon: NbGlyph.bolt,
                              onPressed: vpn.busy.contains('probe') ? null : () => vpn.act(vpn.engine.probe, busyKey: 'probe')),
                          NbButton('Smart pick', small: true, kind: NbButtonKind.ghost,
                              onPressed: () => vpn.act(vpn.engine.smart, busyKey: 'fastest')),
                          NbButton('Rescan', small: true, kind: NbButtonKind.quiet, icon: NbGlyph.refresh,
                              onPressed: () => vpn.act(vpn.engine.rescan, busyKey: 'rescan')),
                          NbButton('Open folder', small: true, kind: NbButtonKind.quiet,
                              onPressed: () => vpn.act(vpn.engine.openConfigs)),
                        ],
                      ),
                      const SizedBox(height: NbSpace.x3),
                      NbPanel(
                        padding: const EdgeInsets.all(NbSpace.x3),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Wrap(
                              spacing: NbSpace.x3,
                              runSpacing: NbSpace.x3,
                              crossAxisAlignment: WrapCrossAlignment.end,
                              children: [
                                SizedBox(
                                  width: 240,
                                  child: NbTextBox(controller: _q, label: '', hint: 'Search locations…',
                                      onChanged: (_) => setState(() {})),
                                ),
                                NbSelect(
                                  value: _sort,
                                  label: 'Sort servers',
                                  options: const [('best', 'Best latency'), ('name', 'Name A–Z'), ('recent', 'Favorites first')],
                                  onChanged: (v) => setState(() => _sort = v),
                                ),
                                NbChipButton('Favorites', on: _onlyFav, icon: NbGlyph.star,
                                    onTap: () => setState(() => _onlyFav = !_onlyFav)),
                              ],
                            ),
                            const SizedBox(height: NbSpace.x3),
                            if (s.regions.isEmpty)
                              _Empty(text: 'No servers yet. Free servers shows where to get some at no cost.',
                                  action: 'Free servers', onTap: () => showFreeServers(context))
                            else if (rows.isEmpty)
                              const _Empty(text: 'No servers match your search.')
                            else
                              SpringColumn(
                                children: [
                                  for (final r in rows)
                                    Padding(
                                      key: ValueKey(r.name),
                                      padding: const EdgeInsets.only(bottom: 4),
                                      child: ServerRow(
                                        region: r,
                                        active: s.connected && s.active == r.name,
                                        connecting: s.connecting == r.name,
                                        favorite: s.favorites.contains(r.name),
                                        onTap: vpn.online
                                            ? () => s.connected && s.active == r.name
                                                  ? vpn.act(vpn.engine.disconnect)
                                                  : vpn.connect(r.name)
                                            : null,
                                        onStar: () => vpn.act(() => vpn.engine.favorite(r.name)),
                                        onEdit: () => openEditor(context, name: r.name),
                                      ),
                                    ),
                                ],
                              ),
                          ],
                        ),
                      ),
                      const SizedBox(height: NbSpace.x3),
                      Text('Measured from this PC. While connected, other servers are measured through the tunnel and '
                          'marked ≈ as estimates.', style: NbType.text(12, c.dim, height: 1.5)),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.text, this.action, this.onTap});
  final String text;
  final String? action;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
      decoration: BoxDecoration(borderRadius: NbRadius.rowAll, border: Border.all(color: c.line2)),
      child: Column(
        children: [
          Text(text, textAlign: TextAlign.center, style: NbType.text(14, c.muted, height: 1.5)),
          if (action != null) ...[const SizedBox(height: 12), NbButton(action!, onPressed: onTap)],
        ],
      ),
    );
  }
}
