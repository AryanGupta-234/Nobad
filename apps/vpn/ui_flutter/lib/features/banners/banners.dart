/// The notices about protection and setup (app_ext.js updateBanners): a failed connect with its actions, Windows
/// Firewall off, WireGuard missing or installing, the kill switch blocking, an update, a crash report.
/// Same conditions, same words, same actions as the WebView UI.
library;

import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/tokens.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../state/vpn_controller.dart';
import '../../widgets/panels.dart';
import '../actions.dart';
import '../onboarding/setup.dart';

/// Error titles rebuilt from the known codes (app_ext.js ERR_TITLES / ERR_DETAILS).
const errTitles = {
  'handshake': '{name} never completed a handshake',
  'start_failed': "Couldn't start {name}",
  'bad_config': "Can't read the config for {name}",
  'dns_endpoint': "Can't find the server address for {name}",
  'wg_missing': "WireGuard for Windows isn't installed",
  'not_admin': 'NOBAD needs administrator rights',
  'captive': 'Wi-Fi sign-in required',
  'reconnect_failed': "Couldn't reconnect",
};

String errorTitle(EngineError e) =>
    errTitles.containsKey(e.code) ? errTitles[e.code]!.replaceAll('{name}', e.name ?? '') : e.title;

class Banners extends StatefulWidget {
  const Banners({super.key});
  @override
  State<Banners> createState() => _BannersState();
}

class _BannersState extends State<Banners> {
  /// Notices the user closed, by their exact content (a new error shows again).
  final _hidden = <String>{};
  bool _updateLater = false, _crashDismissed = false;
  Timer? _expire;
  int _errTs = -1;

  @override
  void dispose() {
    _expire?.cancel();
    super.dispose();
  }

  void _armExpiry(VpnController vpn, EngineError e) {
    if (e.ts == _errTs) return;
    _errTs = e.ts;
    _expire?.cancel();
    if (e.transient) {
      // a failed attempt is news, not a state: it closes by itself after 15 s
      _expire = Timer(const Duration(seconds: 15), () => vpn.act(vpn.engine.dismissError));
    }
  }

  void _action(BuildContext context, VpnController vpn, EngineError e, String id) {
    final st = vpn.state;
    switch (id) {
      case 'retry':
        final n = e.name ?? st?.lastRegion;
        vpn.act(vpn.engine.dismissError);
        if (n != null) vpn.connect(n);
      case 'check_endpoint':
        if (e.name != null) vpn.act(() => vpn.engine.endpointCheck(e.name!), done: 'Checking endpoint…');
      case 'install_wg':
        vpn.act(vpn.engine.installWireguard, done: 'Installing WireGuard…');
      case 'elevate':
        vpn.act(vpn.engine.elevate);
      case 'edit_config':
        if (e.name != null) openEditor(context, name: e.name);
      case 'panic':
        panic(context);
      case 'open_portal':
        vpn.act(() => vpn.engine.openUrl('portal'));
      case 'show_log':
        AppScope.of(context).nav.go(AppTab.settings);
      case 'dismiss':
        vpn.act(vpn.engine.dismissError);
    }
  }

  @override
  Widget build(BuildContext context) {
    final vpn = AppScope.of(context).vpn;
    return ListenableBuilder(
      listenable: vpn,
      builder: (context, _) {
        final st = vpn.state;
        if (st == null) return const SizedBox.shrink();
        final out = <Widget>[];
        void add(String id, Notice n) {
          final sig = '$id|${n.title}|${n.detail}';
          if (_hidden.contains(sig)) return;
          out.add(Padding(
            key: ValueKey(id),
            padding: const EdgeInsets.only(bottom: NbSpace.x2),
            child: Notice(
              kind: n.kind,
              title: n.title,
              detail: n.detail,
              actions: n.actions,
              onClose: n.onClose == null ? null : () {
                setState(() => _hidden.add(sig));
                n.onClose!();
              },
            ),
          ));
        }

        final e = st.error;
        if (e != null) {
          _armExpiry(vpn, e);
          add('error', Notice(
            kind: e.code == 'captive' ? NoticeKind.warn : NoticeKind.bad,
            title: errorTitle(e),
            detail: e.detail,
            actions: [for (final a in e.actions) NoticeAction(a.label, () => _action(context, vpn, e, a.id))],
            onClose: () => vpn.act(vpn.engine.dismissError),
          ));
        }
        if (st.fwOff && (st.setting('kill_switch') || st.setting('dns_leak_block'))) {
          add('fwoff', Notice(
            kind: NoticeKind.bad,
            title: 'Protection not enforced',
            detail: "Windows Firewall is off, so the kill switch can't block traffic.",
            actions: [NoticeAction('Turn on Windows Firewall', () => vpn.act(() => vpn.engine.openUrl('firewall_settings')))],
          ));
        }
        if (!st.wireguard && st.wgInstalling) {
          add('wg', const Notice(
            kind: NoticeKind.info,
            title: 'Installing WireGuard…',
            detail: 'NOBAD needs the official WireGuard service. This takes about a minute; no action needed.',
          ));
        } else if (!st.wireguard) {
          add('wg', Notice(
            kind: NoticeKind.warn,
            title: "WireGuard for Windows isn't installed",
            detail: 'NOBAD needs the official WireGuard service to create tunnels.',
            actions: [
              NoticeAction('Install WireGuard', () => vpn.act(vpn.engine.installWireguard, done: 'Installing WireGuard…')),
              NoticeAction('Open setup', () => showSetup(context)),
            ],
          ));
        }
        if (st.ksActive && !st.connected && st.connecting == null) {
          add('ksblock', Notice(
            kind: NoticeKind.warn,
            title: 'Kill switch is blocking your internet',
            detail: "You're not connected, so non-VPN traffic is blocked. Reconnect, or restore normal internet.",
            actions: [NoticeAction('Restore internet', () => panic(context), primary: true)],
          ));
        }
        final u = st.update;
        if (u != null && u.available && !_updateLater) {
          add('update', Notice(
            kind: NoticeKind.info,
            title: 'Update available: ${u.version}',
            detail: u.notes,
            actions: [
              NoticeAction('Install now', () => vpn.act(vpn.engine.updateInstall)),
              NoticeAction('Later', () => setState(() => _updateLater = true)),
            ],
          ));
        }
        if (st.crashPending > 0 && !_crashDismissed) {
          add('crash', Notice(
            kind: NoticeKind.info,
            title: 'NOBAD closed unexpectedly last time',
            detail: 'A crash report was saved on this PC. Nothing is sent unless you choose to.',
            actions: [
              NoticeAction('Report it', () => vpn.act(() => vpn.engine.reportProblem(crash: true), done: 'Preparing your report…')),
              NoticeAction('Dismiss', () => setState(() => _crashDismissed = true)),
            ],
          ));
        }
        if (out.isEmpty) return const SizedBox.shrink();
        return ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: out),
        );
      },
    );
  }
}
