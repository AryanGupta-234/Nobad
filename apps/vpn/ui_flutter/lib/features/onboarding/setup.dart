/// "Set up NOBAD": the first-run checklist (app_ext.js wizardOpen). It checks what NOBAD needs and offers a fix
/// for anything missing; it updates by itself as the engine's state changes.
library;

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../widgets/controls.dart';
import '../../widgets/dialogs.dart';
import '../../widgets/icons.dart';
import '../actions.dart';
import 'free_servers.dart';

Future<void> showSetup(BuildContext context) => showScoped<void>(context, (ctx) => const SetupChecklist());

class SetupChecklist extends StatelessWidget {
  const SetupChecklist({super.key});

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final vpn = scope.vpn;
    return ListenableBuilder(
      listenable: vpn,
      builder: (context, _) {
        final st = vpn.state ?? const VpnState();
        final ready = st.wireguard && st.admin && st.regions.isNotEmpty;
        return NbDialog(
          width: 700,
          title: 'Set up NOBAD',
          body: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('NOBAD checks what it needs and offers a fix for anything missing.'),
              const SizedBox(height: NbSpace.x4),
              _Item(
                ok: st.wireguard,
                title: 'WireGuard for Windows',
                desc: st.wireguard ? 'Installed.' : 'Not found. NOBAD uses the official WireGuard service.',
                actions: st.wireguard
                    ? const []
                    : [
                        ('Install WireGuard', () => vpn.act(vpn.engine.installWireguard, done: 'Installing WireGuard…')),
                        ('Open download page', () => vpn.act(() => vpn.engine.openUrl('wireguard_install'))),
                      ],
              ),
              _Item(
                ok: st.admin,
                title: 'Administrator rights',
                desc: st.admin ? 'Running as administrator.' : 'Needed for tunnels and firewall rules.',
                actions: st.admin ? const [] : [('Relaunch as administrator', () => vpn.act(vpn.engine.elevate))],
              ),
              _Item(
                ok: st.regions.isNotEmpty,
                title: 'A server config',
                desc: st.regions.isNotEmpty
                    ? '${st.regions.length} server(s) found.'
                    : 'Import a WireGuard .conf from your provider.',
                actions: [
                  ('Free servers', () => showFreeServers(context)),
                  ('Choose files…', () => importFiles(context)),
                  ('From URL', () => importUrl(context)),
                  ('Paste', () => openEditor(context)),
                  ('Open folder', () => vpn.act(vpn.engine.openConfigs)),
                ],
              ),
              _Item(
                ok: true,
                title: 'Optional',
                desc: 'You can change these any time in Settings.',
                child: Wrap(
                  spacing: NbSpace.x5,
                  runSpacing: NbSpace.x2,
                  children: [
                    for (final (k, label) in [
                      ('kill_switch', 'Kill switch'),
                      ('dns_leak_block', 'DNS leak block'),
                      ('start_with_windows', 'Start with Windows'),
                      if (st.tray) ('tray', 'Tray icon'),
                      ('ip_lookup', 'Show my location and exit IP (uses ipinfo.io)'),
                    ])
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          NbSwitch(
                            value: st.setting(k),
                            label: label,
                            onChanged: (v) => vpn.act(() => vpn.engine.setSetting(k, v)),
                          ),
                          const SizedBox(width: 8),
                          Text(label, style: NbType.text(13, NbColors.of(context).text)),
                        ],
                      ),
                  ],
                ),
              ),
            ],
          ),
          actions: [
            NbButton('Re-check', kind: NbButtonKind.ghost, onPressed: vpn.refresh),
            NbButton(ready ? 'Finish' : 'Skip for now', onPressed: () {
              vpn.act(vpn.engine.wizardDone);
              Navigator.pop(context);
            }),
          ],
        );
      },
    );
  }
}

class _Item extends StatelessWidget {
  const _Item({required this.ok, required this.title, required this.desc, this.actions = const [], this.child});
  final bool ok;
  final String title;
  final String desc;
  final List<(String, VoidCallback)> actions;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Semantics(
      label: ok ? 'Done' : 'Needs attention',
      container: true,
      child: Padding(
        padding: const EdgeInsets.only(bottom: NbSpace.x4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 26,
              height: 26,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: (ok ? c.sealed : c.amber).withValues(alpha: .14),
                border: Border.all(color: (ok ? c.sealed : c.amber).withValues(alpha: .6)),
              ),
              child: ok
                  ? NbIcon(NbGlyph.check, size: 16, color: c.sealed, stroke: 2)
                  : Text('!', style: NbType.text(13, c.amber, weight: FontWeight.w600)),
            ),
            const SizedBox(width: NbSpace.x3),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: NbType.text(14, c.text, weight: FontWeight.w600)),
                  Text(desc, style: NbType.text(13, c.muted, height: 1.5)),
                  if (actions.isNotEmpty) ...[
                    const SizedBox(height: NbSpace.x2),
                    Wrap(spacing: NbSpace.x2, runSpacing: NbSpace.x2, children: [
                      for (final (l, f) in actions) NbButton(l, small: true, kind: NbButtonKind.ghost, onPressed: f),
                    ]),
                  ],
                  if (child != null) ...[const SizedBox(height: NbSpace.x2), child!],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
