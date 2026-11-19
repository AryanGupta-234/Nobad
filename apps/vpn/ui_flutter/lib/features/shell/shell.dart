/// The main window's frame: the live world map as the backdrop, the rail (Home, Servers, Settings), the screen,
/// toasts, the splash while NOBAD starts, and the honest "not running" state when there's no engine.
library;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../map/world.dart';
import '../../map/world_map.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/motion.dart';
import '../../widgets/panels.dart';
import '../../widgets/pressable.dart';
import '../home/home_screen.dart';
import '../onboarding/setup.dart';
import '../servers/servers_screen.dart';
import '../settings/settings_screen.dart';
import 'splash.dart';

/// Servers as map pins: where the engine located each endpoint, else a place read from its name or country.
List<MapPin> pinsOf(VpnState s) {
  final out = <MapPin>[];
  for (final r in s.regions) {
    final at = (r.lat != null && r.lon != null) ? (r.lat!, r.lon!) : (guessPlace(r.name) ?? countryPoint(r.country));
    if (at == null) continue;
    out.add(MapPin(r.name, at.$1, at.$2,
        active: s.connected && s.active == r.name, connecting: s.connecting == r.name, grade: r.ping?.grade ?? 'none'));
  }
  return out;
}

/// This PC on the map: the located home, else its country, else the time zone's longitude.
(double, double) homeOf(VpnState s, DateTime now) {
  final lat = jNum(s.home['lat']), lon = jNum(s.home['lon']);
  if (lat != null && lon != null) return (lat, lon);
  final byCountry = countryPoint(jStr(s.home['country']));
  return byCountry ?? (25.0, now.timeZoneOffset.inMinutes / 60 * 15);
}

class Shell extends StatefulWidget {
  const Shell({super.key, this.version = '', this.splash = true, this.now});
  final String version;
  final bool splash;
  final DateTime Function()? now;
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  bool _setupShown = false;
  late bool _splash = widget.splash;
  final _keys = FocusNode(debugLabel: 'window keys');

  @override
  void dispose() {
    _keys.dispose();
    super.dispose();
  }

  void _maybeSetup(VpnState? s) {
    if (_setupShown || _splash || s == null || s.wizardDone) return;
    _setupShown = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) showSetup(context);
    });
  }

  @override
  Widget build(BuildContext context) {
    final scope = AppScope.of(context);
    final nav = scope.nav;
    final now = widget.now ?? DateTime.now;
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.digit1, control: true): () => nav.go(AppTab.home),
        const SingleActivator(LogicalKeyboardKey.digit2, control: true): () => nav.go(AppTab.servers),
        const SingleActivator(LogicalKeyboardKey.digit3, control: true): () => nav.go(AppTab.settings),
      },
      child: Focus(
        focusNode: _keys,
        autofocus: true,
        child: ListenableBuilder(
          listenable: Listenable.merge([scope.vpn, nav]),
          builder: (context, _) {
            final c = NbColors.of(context);
            final vpn = scope.vpn;
            final s = vpn.state;
            _maybeSetup(s);
            final tone = switch (s?.protection) {
              Protection.protected => c.sealed,
              Protection.connecting => c.amber,
              Protection.blocked => c.blocked,
              _ => null,
            };
            return Stack(
              children: [
                Positioned.fill(child: Backdrop(tone: tone)),
                Positioned.fill(
                  left: 88,
                  child: AnimatedOpacity(
                    opacity: nav.value == AppTab.home && !_splash ? .3 : .45, // Home has its own map; this one only fills the gaps
                    duration: NbMotion.of(context, NbMotion.slow),
                    child: WorldMap(
                    pins: s == null ? const [] : pinsOf(s),
                    home: s == null ? null : homeOf(s, now()),
                    protected: s?.connected ?? false,
                    now: widget.now,
                  ),
                  ),
                ),
                if (!_splash)
                  Row(
                    children: [
                      _Rail(tab: nav.value, onGo: nav.go, protection: s?.protection, version: widget.version),
                      Expanded(
                        child: !vpn.online
                            ? _Offline(link: vpn.link)
                            : AnimatedSwitcher(
                                duration: NbMotion.of(context, NbMotion.slow),
                                switchInCurve: NbMotion.curve,
                                layoutBuilder: (current, previous) =>
                                    Stack(fit: StackFit.expand, children: [...previous, ?current]),
                                transitionBuilder: (child, a) => FadeTransition(
                                  opacity: a,
                                  child: SlideTransition(
                                    position: Tween(begin: const Offset(0, .012), end: Offset.zero).animate(a),
                                    child: child,
                                  ),
                                ),
                                child: KeyedSubtree(
                                  key: ValueKey(nav.value),
                                  child: switch (nav.value) {
                                    AppTab.home => const HomeScreen(),
                                    AppTab.servers => const ServersScreen(),
                                    AppTab.settings => const SettingsScreen(),
                                  },
                                ),
                              ),
                      ),
                    ],
                  ),
                if (_splash) Positioned.fill(child: Splash(vpn: vpn, onDone: () => setState(() => _splash = false))),
                Positioned(right: NbSpace.x4, bottom: NbSpace.x4, child: ToastStack(vpn: vpn)),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _Rail extends StatelessWidget {
  const _Rail({required this.tab, required this.onGo, required this.protection, required this.version});
  final AppTab tab;
  final ValueChanged<AppTab> onGo;
  final Protection? protection;
  final String version;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final dot = switch (protection) {
      Protection.protected => c.sealed,
      Protection.connecting => c.amber,
      Protection.blocked => c.blocked,
      _ => c.dim,
    };
    final word = switch (protection) {
      Protection.protected => 'Protected',
      Protection.connecting => 'Connecting…',
      Protection.blocked => 'Blocked by kill switch',
      Protection.off => 'Not connected',
      null => 'Offline',
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(NbSpace.x3, NbSpace.x3, 0, NbSpace.x3),
      child: Glass(
        level: GlassLevel.panel,
        child: SizedBox(
          width: 64,
          child: Column(
            children: [
              const SizedBox(height: NbSpace.x3),
              const NbMark(size: 28),
              const SizedBox(height: 4),
              Text('VPN', style: NbType.text(12, c.orange, weight: FontWeight.w600).copyWith(letterSpacing: 1.8)),
              const SizedBox(height: NbSpace.x4),
              _RailItems(tab: tab, onGo: onGo),
              const Spacer(),
              Semantics(
                label: word,
                child: Tooltip(
                  message: word,
                  child: AnimatedContainer(
                    duration: NbMotion.of(context, NbMotion.slow),
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: dot,
                      boxShadow: [BoxShadow(color: dot.withValues(alpha: .6), blurRadius: 8)],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 8),
              if (version.isNotEmpty) Text(version, style: NbType.data(12, c.dim)),
              const SizedBox(height: NbSpace.x3),
            ],
          ),
        ),
      ),
    );
  }
}

class _Offline extends StatelessWidget {
  const _Offline({required this.link});
  final Link link;
  @override
  Widget build(BuildContext context) {
    final (title, body) = switch (link) {
      Link.connecting => ('Starting', 'Connecting to NOBAD VPN…'),
      Link.incompatible => ('Update needed', 'This window and NOBAD VPN are different versions. Reinstall NOBAD VPN to bring them together.'),
      Link.refused => ('Not allowed', 'NOBAD VPN refused this program. Open NOBAD VPN from the Start menu or the tray icon.'),
      _ => ('Not running', "NOBAD VPN isn't running. Start it from the Start menu; this window connects by itself when it is. "
          'If the kill switch left you offline, use Start menu → NOBAD VPN → Restore internet.'),
    };
    return Align(
      alignment: Alignment.topLeft,
      child: Padding(
        padding: const EdgeInsets.all(NbSpace.x4),
        child: SizedBox(
          width: 420,
          child: Glass(level: GlassLevel.panel, padding: const EdgeInsets.all(NbSpace.x4), child: PageTitle(title, sub: body)),
        ),
      ),
    );
  }
}

/// The rail's items, with one orange indicator that slides to the selected one.
class _RailItems extends StatelessWidget {
  const _RailItems({required this.tab, required this.onGo});
  final AppTab tab;
  final ValueChanged<AppTab> onGo;
  static const _h = 50.0, _gap = 4.0;
  static const _items = [
    (AppTab.home, NbGlyph.home, 'Home', 'Ctrl+1'),
    (AppTab.servers, NbGlyph.globe, 'Servers', 'Ctrl+2'),
    (AppTab.settings, NbGlyph.settings, 'Settings', 'Ctrl+3'),
  ];

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final i = _items.indexWhere((x) => x.$1 == tab);
    return SizedBox(
      width: 52,
      height: _items.length * (_h + _gap),
      child: Stack(
        children: [
          AnimatedPositioned(
            duration: NbMotion.of(context, NbMotion.slow),
            curve: const SpringCurve(damping: .8, stiffness: 240),
            top: i * (_h + _gap),
            left: 0,
            right: 0,
            height: _h,
            // Fluent: the selected item gets a quiet fill and a short orange pill on its left edge
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
          for (var k = 0; k < _items.length; k++)
            Positioned(
              top: k * (_h + _gap),
              left: 0,
              right: 0,
              height: _h,
              child: Pressable(
                onTap: () => onGo(_items[k].$1),
                selected: tab == _items[k].$1,
                semanticLabel: _items[k].$3,
                tooltip: '${_items[k].$3} (${_items[k].$4})',
                builder: (context, s) {
                  final on = tab == _items[k].$1;
                  return AnimatedContainer(
                    duration: NbMotion.of(context, NbMotion.fast),
                    decoration: BoxDecoration(
                      color: !on && s.lit ? c.raised : null,
                      borderRadius: NbRadius.controlAll,
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        NbIcon(_items[k].$2, size: 16, color: on ? c.orange : (s.lit ? c.text : c.muted)),
                        const SizedBox(height: 3),
                        Text(_items[k].$3,
                            style: NbType.text(12, on ? c.text : c.muted, weight: on ? FontWeight.w600 : FontWeight.w400)),
                      ],
                    ),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}
