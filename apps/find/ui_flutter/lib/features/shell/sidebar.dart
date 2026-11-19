/// The sidebar: Search with its categories (each a pre-filtered search), Index, and Settings with its pages (shown
/// while Settings is open); at the foot, the work level and phase. 200 px, 32 px items, 16 px icons.
library;

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../state/categories.dart';
import '../../widgets/common.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

const categoryGlyphs = {
  SearchCategory.all: NbGlyph.grid,
  SearchCategory.documents: NbGlyph.doc,
  SearchCategory.photos: NbGlyph.image,
  SearchCategory.media: NbGlyph.media,
  SearchCategory.code: NbGlyph.code,
  SearchCategory.downloads: NbGlyph.download,
  SearchCategory.recent: NbGlyph.clock,
};

const settingsGlyphs = {
  SettingsPage.general: NbGlyph.sliders,
  SettingsPage.search: NbGlyph.search,
  SettingsPage.indexing: NbGlyph.drive,
  SettingsPage.models: NbGlyph.chip,
  SettingsPage.performance: NbGlyph.gauge,
  SettingsPage.privacy: NbGlyph.shield,
  SettingsPage.shortcuts: NbGlyph.keyboard,
  SettingsPage.about: NbGlyph.info,
};

class Sidebar extends StatelessWidget {
  const Sidebar({super.key});

  static const width = NbSpace.sidebar;
  static const margin = 8.0;

  /// The room it takes, margin included.
  static const room = width + margin;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(margin, margin, 0, margin),
      child: SizedBox(
        width: width,
        child: Glass(
          level: GlassLevel.panel,
          radius: 12,
          padding: const EdgeInsets.fromLTRB(8, 10, 8, 8),
          child: ListenableBuilder(
            listenable: Listenable.merge([s.nav, s.find]),
            builder: (context, _) {
              final tab = s.nav.tab;
              final cat = SearchCategory.of(s.find.filters);
              void category(SearchCategory k) {
                s.find.setFilters(k.filters);
                s.nav.go(AppTab.search);
              }

              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(6, 0, 6, 12),
                    child: Row(
                      children: [
                        const NbMark(size: 22),
                        const SizedBox(width: 9),
                        Text('NOBAD Find', style: NbType.text(13.5, c.text, weight: FontWeight.w700, height: 1.2)),
                      ],
                    ),
                  ),
                  Expanded(
                    child: ListView(
                      padding: EdgeInsets.zero,
                      children: [
                        _Item(
                          glyph: NbGlyph.search,
                          label: 'Search',
                          keys: 'Ctrl+1',
                          on: tab == AppTab.search && cat == SearchCategory.all,
                          strong: tab == AppTab.search,
                          onTap: () => category(SearchCategory.all),
                        ),
                        for (final k in SearchCategory.values.skip(1))
                          _Item(
                            glyph: categoryGlyphs[k]!,
                            label: k.label,
                            indent: true,
                            on: tab == AppTab.search && cat == k,
                            onTap: () => category(k),
                          ),
                        const SizedBox(height: 6),
                        _Item(
                          glyph: NbGlyph.rings,
                          label: 'Index',
                          keys: 'Ctrl+2',
                          on: tab == AppTab.indexing,
                          strong: tab == AppTab.indexing,
                          onTap: () => s.nav.go(AppTab.indexing),
                        ),
                        _Item(
                          glyph: NbGlyph.settings,
                          label: 'Settings',
                          keys: 'Ctrl+3',
                          on: false,
                          strong: tab == AppTab.settings,
                          onTap: () => s.nav.go(AppTab.settings),
                        ),
                        if (tab == AppTab.settings)
                          for (final p in SettingsPage.values)
                            _Item(
                              glyph: settingsGlyphs[p]!,
                              label: p.label,
                              indent: true,
                              on: s.nav.page == p,
                              onTap: () => s.nav.showPage(p),
                            ),
                      ],
                    ),
                  ),
                  const _Status(),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class _Item extends StatelessWidget {
  const _Item({
    required this.glyph,
    required this.label,
    required this.on,
    required this.onTap,
    this.keys,
    this.indent = false,
    this.strong = false,
  });
  final NbGlyph glyph;
  final String label;
  final String? keys;
  final bool on;

  /// A top-level item whose section is open (Search, Index, Settings): its label in full text colour.
  final bool strong;
  final bool indent;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final d = NbMotion.of(context, NbMotion.fast);
    return Pressable(
      onTap: onTap,
      selected: on,
      semanticLabel: label,
      tooltip: keys == null ? null : '$label ($keys)',
      ringRadius: const BorderRadius.all(Radius.circular(6)),
      builder: (context, p) => AnimatedContainer(
        duration: d,
        height: 32,
        margin: const EdgeInsets.only(bottom: 1),
        padding: EdgeInsets.only(left: indent ? 22 : 8, right: 8),
        decoration: BoxDecoration(
          color: on ? c.orangeA(c.isDark ? .15 : .11) : (p.lit ? c.cardHover : const Color(0x00000000)),
          borderRadius: const BorderRadius.all(Radius.circular(6)),
        ),
        child: Row(
          children: [
            NbIcon(glyph, size: 16, color: on ? c.orange : (p.lit || strong ? c.text : c.dim), stroke: 1.5),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: NbType.text(
                  13,
                  on || strong || p.lit ? c.text : c.muted,
                  weight: on || (strong && !indent) ? FontWeight.w600 : FontWeight.w500,
                  height: 1.2,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The work level and phase; opens Index.
class _Status extends StatelessWidget {
  const _Status();

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: s.status,
      builder: (context, _) {
        final st = s.status.status;
        final ok = s.status.connected;
        return Pressable(
          onTap: () => s.nav.go(AppTab.indexing),
          semanticLabel: 'Indexing details',
          ringRadius: const BorderRadius.all(Radius.circular(6)),
          builder: (context, p) => Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
            decoration: BoxDecoration(
              color: p.lit ? c.cardHover : null,
              borderRadius: const BorderRadius.all(Radius.circular(6)),
              border: Border.all(color: c.line),
            ),
            child: Row(
              children: [
                LevelGlyph(level: ok ? (st?.levelKey ?? 'light') : 'paused', color: c.orange, dim: c.dim, size: 11),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    ok ? (st?.phaseLabel ?? '') : (s.status.link == Link.connecting ? 'Connecting' : 'Offline'),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: NbType.text(11.5, p.lit ? c.text : c.muted, height: 1.2),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
