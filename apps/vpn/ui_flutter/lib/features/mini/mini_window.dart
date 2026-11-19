/// The tray pop-up (--mini): a frosted pane next to the notification area, Windows' Acrylic behind it. Everything the
/// old mini window had (nobadvpn/ui/mini.html, mini.js): the state, the server, Connect/Disconnect, Fastest, Open
/// NOBAD, the kill switch, the rates; it hides when it loses focus or on Esc. When the engine isn't there it says so
/// in a sentence (the old window could show a raw `{"ok": false}`).
library;

import 'dart:async';

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

/// The mini's words for each state (mini.js draw()).
String miniTitle(Protection p) => switch (p) {
  Protection.protected => 'Protected',
  Protection.connecting => 'Connecting…',
  Protection.blocked => 'Blocked by kill switch',
  Protection.off => 'Not connected',
};

class MiniWindow extends StatefulWidget {
  const MiniWindow({super.key});
  @override
  State<MiniWindow> createState() => MiniWindowState();
}

class MiniWindowState extends State<MiniWindow> {
  String? _picked;
  bool _visible = true, _settling = true;
  Timer? _settle;
  late final AppLifecycleListener _life = AppLifecycleListener(onInactive: () {
    if (_visible && !_settling) hide();
  });

  @override
  void initState() {
    super.initState();
    _life;
    _settle = Timer(const Duration(milliseconds: 500), () => _settling = false);
  }

  @override
  void dispose() {
    _settle?.cancel();
    _life.dispose();
    super.dispose();
  }

  /// A tray click while it's up hides it (Quick view toggles); otherwise it comes up next to the tray.
  void toggle() => _visible ? hide() : show();

  void show() {
    final scope = AppScope.of(context);
    _visible = true;
    _settling = true;
    _settle?.cancel();
    _settle = Timer(const Duration(milliseconds: 500), () => _settling = false);
    scope.window.showMini();
    unawaited(scope.engine.shown(true));
    setState(() {});
  }

  void hide() {
    final scope = AppScope.of(context);
    _visible = false;
    scope.window.hide();
    unawaited(scope.engine.shown(false));
  }

  Future<void> _openMain() async {
    final scope = AppScope.of(context);
    hide();
    try {
      final a = await scope.engine.uiShow('main');
      if (!jBool(a.data['shown']) && !jBool(a.data['launched'])) scope.window.spawn('main');
    } on Object {
      scope.window.spawn('main'); // no engine: the main window says so itself
    }
  }

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final vpn = scope.vpn;
    final c = NbColors.of(context);
    return CallbackShortcuts(
      bindings: {const SingleActivator(LogicalKeyboardKey.escape): hide},
      child: Focus(
        autofocus: true,
        child: Glass(
          level: GlassLevel.card,
          radius: 10,
          fill: c.isDark ? const Color(0x99101218) : const Color(0xB3FFFFFF),
          child: Padding(
            padding: const EdgeInsets.all(NbSpace.x4),
            child: ListenableBuilder(listenable: vpn, builder: (context, _) => _body(context, vpn, c)),
          ),
        ),
      ),
    );
  }

  Widget _body(BuildContext context, VpnController vpn, NbColors c) {
    final s = vpn.state;
    final header = Row(
      children: [
        const NbMark(size: 22),
        const SizedBox(width: 8),
        Text('VPN', style: NbType.text(12, c.orange, weight: FontWeight.w600).copyWith(letterSpacing: 2.2)),
        const Spacer(),
        NbButton('Open NOBAD', small: true, kind: NbButtonKind.quiet, icon: NbGlyph.external, onPressed: _openMain),
      ],
    );
    if (!vpn.online || s == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          header,
          const Spacer(),
          Text('OFFLINE', style: NbType.display(NbSize.page, c.text)),
          const SizedBox(height: 10),
          Text(
            vpn.link == Link.connecting
                ? 'Connecting to NOBAD VPN…'
                : "NOBAD VPN isn't running. Start it from the Start menu.",
            style: NbType.text(13, c.muted, height: 1.5),
          ),
          const Spacer(),
        ],
      );
    }
    final p = s.protection;
    final names = [for (final r in s.regions) r.name];
    final on = s.connected, wait = s.connecting != null;
    final cur = (on ? s.active : null) ?? (wait ? s.connecting : null) ?? _picked ?? s.lastRegion ?? '';
    final sel = names.contains(cur) ? cur : (names.isEmpty ? '' : names.first);
    final sub = on ? (s.active ?? '') : (wait ? (s.connecting ?? '') : (s.note ?? ''));
    final tone = switch (p) {
      Protection.protected => c.sealed,
      Protection.connecting => c.amber,
      Protection.blocked => c.blocked,
      Protection.off => c.text,
    };
    final goLabel = on ? 'Disconnect' : (wait ? 'Connecting…' : 'Connect');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        header,
        const SizedBox(height: 12),
        Row(
          children: [
            Aperture(
              protection: p,
              label: on ? 'Off' : (wait ? '…' : 'On'),
              size: 84,
              onTap: (wait || (!on && names.isEmpty)) ? null : () => on ? vpn.act(vpn.engine.disconnect) : vpn.connect(sel),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Semantics(
                    liveRegion: true,
                    child: Text(miniTitle(p), style: NbType.text(NbSize.lead, tone, weight: FontWeight.w600, height: 1.25)),
                  ),
                  const SizedBox(height: 3),
                  Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.data(12, c.muted)),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (names.isNotEmpty)
          NbSelect(
            value: sel,
            label: 'Server',
            maxWidth: 400,
            options: [for (final n in names) (n, n)],
            onChanged: (v) => setState(() => _picked = v),
          )
        else
          Text('No servers yet. Open NOBAD to add some.', style: NbType.text(13, c.muted)),
        const SizedBox(height: 10),
        SizedBox(
          height: 30,
          child: NbButton(
            goLabel,
            kind: on ? NbButtonKind.ghost : NbButtonKind.primary,
            onPressed: wait || (!on && names.isEmpty) ? null : () => on ? vpn.act(vpn.engine.disconnect) : vpn.connect(sel),
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: NbButton('Fastest', kind: NbButtonKind.ghost, icon: NbGlyph.bolt,
                  onPressed: wait || names.isEmpty ? null : () => vpn.act(vpn.engine.fastest, busyKey: 'fastest')),
            ),
          ],
        ),
        const Spacer(),
        Row(
          children: [
            NbSwitch(
              value: s.setting('kill_switch'),
              label: 'Kill switch',
              onChanged: (v) => vpn.act(() => vpn.engine.setSetting('kill_switch', v)),
            ),
            const SizedBox(width: 10),
            Text('Kill switch', style: NbType.text(13, c.muted)),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('↓ ${on && vpn.samples.rx.isNotEmpty ? rate(vpn.traffic.rxBps) : '—'}', style: NbType.data(12, c.muted)),
            Text('↑ ${on && vpn.samples.tx.isNotEmpty ? rate(vpn.traffic.txBps) : '—'}', style: NbType.data(12, c.muted)),
          ],
        ),
      ],
    );
  }
}
