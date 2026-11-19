/// The rail: the mark, Search / Index / Settings, and at the foot the work level as its glyph with the phase.
library;

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../widgets/common.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

class Rail extends StatelessWidget {
  const Rail({super.key});

  static const width = 92.0;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return Container(
      width: width,
      padding: const EdgeInsets.fromLTRB(0, NbSpace.x4, 0, NbSpace.x4),
      decoration: BoxDecoration(color: c.rail, border: Border(right: BorderSide(color: c.line))),
      child: ListenableBuilder(
        listenable: s.nav,
        builder: (context, _) => Column(children: [
          const NbMark(size: 36),
          const SizedBox(height: NbSpace.x6),
          for (final (tab, glyph, label, key) in const [
            (AppTab.search, NbGlyph.search, 'Search', 'Ctrl+1'),
            (AppTab.indexing, NbGlyph.rings, 'Index', 'Ctrl+2'),
            (AppTab.settings, NbGlyph.settings, 'Settings', 'Ctrl+3'),
          ])
            _RailTab(glyph: glyph, label: label, keys: key, on: s.nav.tab == tab, onTap: () => s.nav.go(tab)),
          const Spacer(),
          ListenableBuilder(
            listenable: s.status,
            builder: (context, _) {
              final st = s.status.status;
              final ok = s.status.connected;
              return Pressable(
                onTap: () => s.nav.go(AppTab.indexing),
                semanticLabel: 'Indexing details',
                focusRing: true,
                builder: (context, p) => Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
                  child: Column(children: [
                    LevelGlyph(level: ok ? (st?.levelKey ?? 'light') : 'paused', color: c.orange, dim: c.dim,
                        size: 12),
                    const SizedBox(height: 8),
                    Text(
                      ok ? (st?.phaseLabel ?? '') : (s.status.link == Link.connecting ? 'Connecting' : 'Offline'),
                      textAlign: TextAlign.center,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: NbType.text(NbSize.micro, p.lit ? c.text : c.dim, height: 1.3),
                    ),
                  ]),
                ),
              );
            },
          ),
        ]),
      ),
    );
  }
}

class _RailTab extends StatelessWidget {
  const _RailTab({required this.glyph, required this.label, required this.keys, required this.on,
      required this.onTap});
  final NbGlyph glyph;
  final String label;
  final String keys;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final d = NbMotion.of(context, NbMotion.base);
    return Padding(
      padding: const EdgeInsets.only(bottom: NbSpace.x1),
      child: Pressable(
        onTap: onTap,
        selected: on,
        semanticLabel: label,
        tooltip: '$label ($keys)',
        ringRadius: NbRadius.rowAll,
        builder: (context, p) => SizedBox(
          width: Rail.width,
          child: Stack(children: [
            // the signal: an orange bar at the rail's edge marks where you are
            Positioned(
              left: 0,
              top: 14,
              bottom: 14,
              child: AnimatedContainer(
                duration: d,
                curve: NbMotion.curve,
                width: on ? 3 : 0,
                decoration: BoxDecoration(
                  color: c.orange,
                  borderRadius: const BorderRadius.horizontal(right: Radius.circular(3)),
                  boxShadow: [if (on && c.isDark) BoxShadow(color: c.orangeA(.7), blurRadius: 10)],
                ),
              ),
            ),
            Center(
              child: AnimatedContainer(
                duration: d,
                width: 70,
                margin: const EdgeInsets.symmetric(vertical: 4),
                padding: const EdgeInsets.symmetric(vertical: 7),
                decoration: BoxDecoration(
                  color: on ? c.orangeA(c.isDark ? .09 : .07) : (p.lit ? c.line : const Color(0x00000000)),
                  borderRadius: NbRadius.rowAll,
                ),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  NbIcon(glyph, size: 20, color: on ? c.orange : (p.lit ? c.text : c.dim)),
                  const SizedBox(height: 4),
                  Text(label,
                      style: NbType.text(NbSize.micro + .5, on ? c.orange : (p.lit ? c.text : c.muted),
                          weight: on ? FontWeight.w600 : FontWeight.w500, height: 1.2)),
                ]),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
