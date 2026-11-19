/// Home, shown while the box and the filters are empty: the one display line, examples to try, quick tiles
/// (the same filters as the bar), files changed lately, and the keys.
///
/// "Recently changed" is asked for when Home appears, when the engine connects, and again when the index grows
/// (status events, at most every 15 s) or after a failed try. The engine sends its usual answer; 8 are shown.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart' show Link;
import '../../engine/models/result.dart';
import '../../widgets/common.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/panels.dart';
import '../../widgets/pressable.dart';

const homeExamples = [
  'rent pdf from last week',
  'beach photos in march',
  'budget.xlsx',
  'newest in my downloads',
  'video bigger than 100 mb',
];

/// (badge, label, words, filters): 0.7.0 TILES.
const homeTiles = [
  ('PDF', 'PDFs', '', SearchFilters(kind: 'pdf')),
  ('IMG', 'Photos', '', SearchFilters(kind: 'image')),
  ('DOC', 'Documents', '', SearchFilters(kind: 'document')),
  ('XLS', 'Spreadsheets', '', SearchFilters(kind: 'spreadsheet')),
  ('DIR', 'Downloads folder', 'in my downloads', SearchFilters.none),
  ('NEW', 'Recent', '', SearchFilters(modified: 'week', sort: 'newest')),
];

class HomeView extends StatefulWidget {
  const HomeView({super.key, required this.onExample, required this.onTile});
  final ValueChanged<String> onExample;
  final void Function(String words, SearchFilters filters) onTile;

  @override
  State<HomeView> createState() => _HomeViewState();
}

class _HomeViewState extends State<HomeView> {
  List<FileResult>? _recent;
  DateTime _asked = DateTime.fromMillisecondsSinceEpoch(0);
  int _files = -1;
  AppScope? _scope;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (_scope != null) return; // once: the scope is rebuilt with the app, its controllers stay the same
    _scope?.status.removeListener(_statusChanged);
    _scope = s;
    s.status.addListener(_statusChanged);
    s.engine.link.addListener(_linkChanged);
    _files = s.status.status?.files ?? -1;
    unawaited(_load());
  }

  bool _failed = false;

  void _linkChanged() {
    if (_scope!.engine.link.value == Link.connected) unawaited(_load());
  }

  void _statusChanged() {
    final n = _scope!.status.status?.files ?? -1;
    if (_failed) {
      unawaited(_load());
      return;
    }
    if (n == _files) return;
    _files = n;
    if (DateTime.now().difference(_asked) > const Duration(seconds: 15)) unawaited(_load());
  }

  Future<void> _load() async {
    _asked = DateTime.now();
    try {
      final a = await _scope!.engine.search('', filters: const SearchFilters(sort: 'newest'));
      _failed = false;
      if (!mounted) return;
      setState(
        () => _recent = [
          for (final r in a.results)
            if (r.kind != 'folder') r,
        ].take(8).toList(),
      );
    } on Object {
      _failed = true; // tried again on the next status or when the engine comes back
      if (mounted) setState(() => _recent ??= const []);
    }
  }

  @override
  void dispose() {
    _scope?.status.removeListener(_statusChanged);
    _scope?.engine.link.removeListener(_linkChanged);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final s = AppScope.of(context);
    final hero = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          header: true,
          child: Text('Find anything on this PC.'.toUpperCase(), style: NbType.display(NbSize.hero, c.text)),
        ),
        const SizedBox(height: NbSpace.x4),
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Text(
            'Search by name, by the words inside a file, or by what it was about. Add a kind, a time, a folder '
            'or a size to the words, or pick filters above.',
            style: NbType.text(15, c.muted, height: 1.6),
          ),
        ),
        const SizedBox(height: NbSpace.x5),
        Semantics(
          label: 'Examples to try',
          container: true,
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [for (final e in homeExamples) _Example(e, onTap: () => widget.onExample(e))],
          ),
        ),
      ],
    );
    final browse = Semantics(
      label: 'Browse by kind',
      container: true,
      child: TileGrid(
        min: 180,
        gap: 12,
        children: [
          for (final (badge, label, words, f) in homeTiles)
            _Tile(badge: badge, label: label, onTap: () => widget.onTile(words, f)),
        ],
      ),
    );
    final recent = Glass(
      radius: 26,
      padding: const EdgeInsets.fromLTRB(8, 18, 8, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: Semantics(
              header: true,
              child: Text('Recently changed', style: NbType.text(NbSize.title, c.text, weight: FontWeight.w600)),
            ),
          ),
          _RecentList(
            files: _recent,
            onOpen: (r) async {
              final res = await s.engine.open(r.id);
              if (!res.ok) {
                s.toasts.show(res.error.isNotEmpty ? res.error : "That file isn't there any more.");
              } else if (s.settings.settings.flag('hide_after_open')) {
                s.window.hide();
                unawaited(s.engine.uiHidden('main').catchError((Object _) {}));
              }
            },
          ),
        ],
      ),
    );
    const keys = KeyHints([
      (['↑', '↓'], 'move'),
      (['Enter'], 'open'),
      (['Ctrl', 'Enter'], 'show in folder'),
      (['Ctrl', 'C'], 'copy path'),
      (['Esc'], 'hide'),
    ]);
    // a bento: the big line and the kinds on the left, what changed lately on the right; one column when narrow
    return LayoutBuilder(
      builder: (context, box) {
        final wide = box.maxWidth >= 1040;
        return SingleChildScrollView(
          padding: EdgeInsets.fromLTRB(NbSpace.x6, wide ? NbSpace.x10 : NbSpace.x6, NbSpace.x5, NbSpace.x8),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1320),
              child: wide
                  ? Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          flex: 7,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [hero, const SizedBox(height: 40), browse, const SizedBox(height: 28), keys],
                          ),
                        ),
                        const SizedBox(width: 28),
                        Expanded(flex: 5, child: recent),
                      ],
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        hero,
                        const SizedBox(height: 28),
                        browse,
                        const SizedBox(height: 20),
                        recent,
                        const SizedBox(height: 20),
                        keys,
                      ],
                    ),
            ),
          ),
        );
      },
    );
  }
}

class _Example extends StatelessWidget {
  const _Example(this.text, {required this.onTap});
  final String text;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Pressable(
      onTap: onTap,
      semanticLabel: text,
      ringRadius: NbRadius.pillAll,
      builder: (context, p) => AnimatedContainer(
        duration: NbMotion.of(context, NbMotion.fast),
        padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 6),
        decoration: BoxDecoration(
          color: p.lit ? c.orangeA(.08) : const Color(0x00000000),
          border: Border.all(color: p.lit ? c.orangeA(.7) : c.line2),
          borderRadius: NbRadius.pillAll,
        ),
        child: Text('“$text”', style: NbType.text(13, p.lit ? c.orange : c.muted, height: 1.3)),
      ),
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile({required this.badge, required this.label, required this.onTap});
  final String badge;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      ringRadius: NbRadius.rowAll,
      builder: (context, p) => AnimatedContainer(
        duration: NbMotion.of(context, NbMotion.fast),
        padding: const EdgeInsets.all(12),
        decoration: ShapeDecoration(
          color: p.lit ? c.cardHover : c.card,
          shape: RoundedSuperellipseBorder(
            borderRadius: BorderRadius.circular(20),
            side: BorderSide(color: p.lit ? c.orangeA(.55) : c.line),
          ),
        ),
        child: Row(
          children: [
            Container(
              width: 38,
              height: 38,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                border: Border.all(color: c.line2),
                borderRadius: NbRadius.controlAll,
              ),
              child: Text(badge, style: NbType.data(9.5, c.orange, weight: FontWeight.w700)),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(label, style: NbType.text(14, c.text, weight: FontWeight.w600)),
            ),
          ],
        ),
      ),
    );
  }
}

class _RecentList extends StatelessWidget {
  const _RecentList({required this.files, required this.onOpen});
  final List<FileResult>? files;
  final ValueChanged<FileResult> onOpen;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final list = files;
    return ClipRRect(
      borderRadius: NbRadius.rowAll,
      child: list == null
          ? const SizedBox(height: 48)
          : list.isEmpty
          ? Padding(
              padding: const EdgeInsets.all(14),
              child: Text('Files you change will show up here once they are indexed.', style: NbType.text(13, c.dim)),
            )
          : Column(
              children: [
                for (var i = 0; i < list.length; i++) ...[
                  if (i > 0) Container(height: 1, margin: const EdgeInsets.symmetric(horizontal: 12), color: c.line),
                  Pressable(
                    onTap: () => onOpen(list[i]),
                    semanticLabel: list[i].name,
                    focusRing: false,
                    builder: (context, p) => AnimatedContainer(
                      duration: NbMotion.of(context, NbMotion.fast),
                      color: p.lit ? c.orangeA(.07) : const Color(0x00000000),
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      child: Row(
                        children: [
                          KindBadge(list[i].kind, size: 34),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  list[i].name,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: NbType.text(13.5, p.focus ? c.orange : c.text, weight: FontWeight.w600),
                                ),
                                Text(
                                  list[i].dir,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: NbType.data(NbSize.micro + .5, c.dim),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 12),
                          Text(list[i].ago, style: NbType.data(NbSize.micro + .5, c.dim)),
                        ],
                      ),
                    ),
                  ),
                ],
              ],
            ),
    );
  }
}
