/// Home, shown while the box and the filters are empty: the one display line, examples to try, quick tiles
/// (the same filters as the bar), files changed lately, and the keys.
///
/// "Recently changed" is asked for once when Home appears and again only when the index grows (status events),
/// at most every 15 s, and asks for 8 rows, not 500 (a 0.7.0 review note).
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/result.dart';
import '../../widgets/common.dart';
import '../../widgets/controls.dart';
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
    _files = s.status.status?.files ?? -1;
    unawaited(_load());
  }

  void _statusChanged() {
    final n = _scope!.status.status?.files ?? -1;
    if (n == _files) return;
    _files = n;
    if (DateTime.now().difference(_asked) > const Duration(seconds: 15)) unawaited(_load());
  }

  Future<void> _load() async {
    _asked = DateTime.now();
    try {
      final a = await _scope!.engine.search('', filters: const SearchFilters(sort: 'newest'));
      if (!mounted) return;
      setState(
        () => _recent = [
          for (final r in a.results)
            if (r.kind != 'folder') r,
        ].take(8).toList(),
      );
    } on Object {
      if (mounted) setState(() => _recent ??= const []);
    }
  }

  @override
  void dispose() {
    _scope?.status.removeListener(_statusChanged);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final s = AppScope.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(NbSpace.x8, NbSpace.x8, NbSpace.x8, NbSpace.x8),
      child: Align(
        alignment: Alignment.topLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 800),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Semantics(
                header: true,
                child: Text('Find anything on this PC.'.toUpperCase(), style: NbType.display(NbSize.hero, c.text)),
              ),
              const SizedBox(height: NbSpace.x4),
              const SignalRule(),
              const SizedBox(height: NbSpace.x4),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 560),
                child: Text(
                  'Search by name, by the words inside a file, or by what it was about. Add a kind, a time, a folder '
                  'or a size to the words, or pick filters above.',
                  style: NbType.text(NbSize.body, c.muted, height: 1.55),
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
              const SectionTitle('Browse', top: NbSpace.x8),
              Semantics(
                label: 'Browse by kind',
                container: true,
                child: TileGrid(
                  min: 200,
                  children: [
                    for (final (badge, label, words, f) in homeTiles)
                      _Tile(badge: badge, label: label, onTap: () => widget.onTile(words, f)),
                  ],
                ),
              ),
              const SectionTitle('Recently changed'),
              _RecentList(
                files: _recent,
                onOpen: (r) async {
                  final res = await s.engine.open(r.id);
                  if (!res.ok) {
                    s.toasts.show(res.error.isNotEmpty ? res.error : "That file isn't there any more.");
                  } else if (s.settings.settings.flag('hide_after_open')) {
                    s.window.hide();
                  }
                },
              ),
              const SizedBox(height: NbSpace.x6),
              const KeyHints([
                (['↑', '↓'], 'move'),
                (['Enter'], 'open'),
                (['Ctrl', 'Enter'], 'show in folder'),
                (['Ctrl', 'C'], 'copy path'),
                (['Esc'], 'hide'),
              ]),
            ],
          ),
        ),
      ),
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
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: c.panel,
          border: Border.all(color: p.lit ? c.orangeA(.6) : c.line),
          borderRadius: NbRadius.rowAll,
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
    return NbPanel(
      padding: EdgeInsets.zero,
      clip: true,
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
                  if (i > 0) Container(height: 1, color: c.line),
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
