/// Smart search (0.8.5), shared by the main window and the quick find bar: the inline ghost completion, the
/// autocomplete list, the understood parts as removable chips, and the best guess card.
///
/// Everything shown here can come from the user's disk (names, folders) or their own typing: plain Text only.
library;

import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/result.dart';
import '../../state/suggest_controller.dart';
import '../../widgets/common.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';

import '../../widgets/pressable.dart';

/// A search box's text with the rest of the best completion drawn after it in a dim colour (only while the caret
/// is at the end). The completion isn't part of the text: Tab or → takes it.
class GhostTextController extends TextEditingController {
  GhostTextController({super.text});

  String _ghost = '';
  Color ghostColor = const Color(0x80808080);
  String get ghost => _ghost;
  set ghost(String g) {
    if (g == _ghost) return;
    _ghost = g;
    notifyListeners();
  }

  /// The caret is at the end with nothing selected: the ghost can show and be taken.
  bool get atEnd => selection.isCollapsed && selection.baseOffset == text.length;

  /// Tab / →: the completion becomes text. False when there was none.
  bool acceptGhost() {
    if (_ghost.isEmpty || !atEnd) return false;
    final t = text + _ghost;
    _ghost = '';
    value = TextEditingValue(
      text: t,
      selection: TextSelection.collapsed(offset: t.length),
    );
    return true;
  }

  @override
  TextSpan buildTextSpan({required BuildContext context, TextStyle? style, required bool withComposing}) {
    final base = super.buildTextSpan(context: context, style: style, withComposing: withComposing);
    if (_ghost.isEmpty || !atEnd || value.composing.isValid) return base;
    return TextSpan(
      style: style,
      children: [
        base,
        TextSpan(
          text: _ghost,
          style: style?.copyWith(color: ghostColor),
        ),
      ],
    );
  }
}

/// The autocomplete rows: history (a clock, with an x to forget it), phrases search understands, names.
class SuggestionList extends StatelessWidget {
  const SuggestionList({super.key, required this.ctl, required this.onPick, this.dense = false, this.maxRows = 8});
  final SuggestController ctl;
  final ValueChanged<Suggestion> onPick;

  /// The bar: rows as tall as its result rows, no frame of its own.
  final bool dense;
  final int maxRows;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: ctl,
      builder: (context, _) {
        if (!ctl.isOpen) return const SizedBox.shrink();
        final rows = ctl.items.take(maxRows).toList();
        final list = Column(
          key: const ValueKey('suggestions'),
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (var i = 0; i < rows.length; i++)
              SuggestionRow(
                s: rows[i],
                typed: ctl.askedFor,
                lit: i == ctl.highlighted,
                dense: dense,
                onTap: () => onPick(rows[i]),
                onHover: () => ctl.hover(i),
                onForget: rows[i].isHistory ? () => ctl.forget(rows[i]) : null,
              ),
          ],
        );
        if (dense) return list;
        // frosted for real (a blur of what's under it) and nearly solid: it floats over the filters and results
        final c = NbColors.of(context);
        return Glass(
          level: GlassLevel.blur,
          radius: 12,
          fill: c.surface.withValues(alpha: c.isDark ? .9 : .94),
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: list,
        );
      },
    );
  }
}

class SuggestionRow extends StatelessWidget {
  const SuggestionRow({
    super.key,
    required this.s,
    required this.typed,
    required this.lit,
    required this.onTap,
    required this.onHover,
    this.onForget,
    this.dense = false,
  });
  final Suggestion s;
  final String typed;
  final bool lit;
  final bool dense;
  final VoidCallback onTap;
  final VoidCallback onHover;
  final VoidCallback? onForget;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final glyph = switch (s.kind) {
      'history' => NbGlyph.clock,
      'filter' => NbGlyph.sliders,
      'folder' => NbGlyph.folder,
      _ => NbGlyph.doc,
    };
    final tag = switch (s.kind) {
      'history' => 'Recent',
      'filter' => 'Filter',
      'folder' => 'Folder',
      _ => '',
    };
    // the typed part plain, the completion bold (what the row adds)
    final lower = s.label.toLowerCase();
    final t = typed.trim().toLowerCase();
    final at = t.isEmpty || s.kind == 'file' || s.kind == 'folder' ? -1 : lower.indexOf(t);
    final label = at == 0
        ? Text.rich(
            TextSpan(
              children: [
                TextSpan(text: s.label.substring(0, t.length)),
                TextSpan(
                  text: s.label.substring(t.length),
                  style: TextStyle(color: c.text, fontWeight: FontWeight.w700),
                ),
              ],
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: NbType.text(dense ? 13.5 : 13.5, c.muted),
          )
        : Text(
            s.label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            softWrap: false,
            style: NbType.text(13.5, c.text, weight: FontWeight.w600),
          );
    return MouseRegion(
      onEnter: (_) => onHover(),
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Semantics(
          button: true,
          selected: lit,
          label: '${tag.isEmpty ? '' : '$tag: '}${s.label}',
          child: AnimatedContainer(
            duration: NbMotion.of(context, NbMotion.fast),
            height: dense ? 36 : 34, // dense: the bar's 38 px rows (BarSize.row) less the 2 px margin
            margin: EdgeInsets.symmetric(horizontal: dense ? 6 : 4, vertical: 1),
            padding: EdgeInsets.only(left: dense ? 12 : 10, right: 6),
            decoration: BoxDecoration(
              color: lit ? c.orangeA(c.isDark ? .16 : .12) : null,
              borderRadius: NbRadius.rowAll,
            ),
            child: Row(
              children: [
                NbIcon(glyph, size: 13, color: s.isHistory ? c.dim : c.orange),
                const SizedBox(width: 10),
                Expanded(flex: 6, child: label),
                if (s.detail.isNotEmpty && (s.kind == 'file' || s.kind == 'folder')) ...[
                  const SizedBox(width: 10),
                  Expanded(flex: 4, child: TailText(s.detail, style: NbType.data(10.5, c.dim))),
                ] else if (tag.isNotEmpty) ...[
                  const SizedBox(width: 10),
                  Text(tag, style: NbType.text(NbSize.micro, s.isHistory ? c.dim : c.orange, weight: FontWeight.w600)),
                ],
                if (onForget != null)
                  Pressable(
                    onTap: onForget,
                    semanticLabel: 'Remove “${s.label}” from search history',
                    tooltip: 'Remove from history',
                    canRequestFocus: false,
                    ringRadius: NbRadius.pillAll,
                    builder: (context, p) => Container(
                      margin: const EdgeInsets.only(left: 6),
                      padding: const EdgeInsets.all(5),
                      decoration: BoxDecoration(color: p.lit ? c.cardHover : null, shape: BoxShape.circle),
                      child: NbIcon(NbGlyph.close, size: 11, color: p.lit ? c.text : c.dim),
                    ),
                  )
                else
                  const SizedBox(width: 6),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// What the question was understood as: one chip per part, each with an x that searches without it.
class PartChips extends StatelessWidget {
  const PartChips({super.key, required this.parts, required this.onWords});
  final List<QueryPart> parts;

  /// Search these words instead (a chip's `without`).
  final ValueChanged<String> onWords;

  @override
  Widget build(BuildContext context) => Wrap(
    spacing: 6,
    runSpacing: 6,
    crossAxisAlignment: WrapCrossAlignment.center,
    children: [for (final p in parts) PartChip(p, onRemove: () => onWords(p.without))],
  );
}

class PartChip extends StatelessWidget {
  const PartChip(this.part, {super.key, this.onRemove});
  final QueryPart part;
  final VoidCallback? onRemove;

  static String caption(String kind) => switch (kind) {
    'folder' => 'in',
    'drive' => 'on',
    'kind' => '',
    'time' => '',
    'size' => '',
    'sort' => '',
    'meaning' => 'about',
    _ => 'words',
  };

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final about = part.isMeaning;
    final fg = about ? c.text : c.orange;
    final cap = caption(part.kind);
    return Container(
      padding: EdgeInsets.fromLTRB(10, 3, onRemove == null ? 10 : 4, 3),
      decoration: BoxDecoration(
        color: about ? c.card : c.orangeA(.07),
        border: Border.all(color: about ? c.line2 : c.orangeA(.5)),
        borderRadius: NbRadius.pillAll,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (cap.isNotEmpty) ...[
            Text(cap, style: NbType.text(NbSize.micro, c.dim, weight: FontWeight.w600, height: 1.3)),
            const SizedBox(width: 4),
          ],
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 260),
            child: Text(
              about ? '“${part.label}”' : part.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: NbType.text(NbSize.small, fg, weight: FontWeight.w600, height: 1.3),
            ),
          ),
          if (onRemove != null)
            Pressable(
              onTap: onRemove,
              semanticLabel: 'Remove ${part.label}',
              tooltip: 'Search without this',
              canRequestFocus: false,
              ringRadius: NbRadius.pillAll,
              builder: (context, p) => Padding(
                padding: const EdgeInsets.only(left: 4),
                child: NbIcon(NbGlyph.close, size: 12, color: p.lit ? c.text : fg),
              ),
            ),
        ],
      ),
    );
  }
}

/// The best guess, at the top of the results: the one file the engine is sure of, framed in warm glass with
/// why it's the guess. The row inside is the normal result row (preview, highlights, actions). Enter opens it.
class BestGuessCard extends StatelessWidget {
  const BestGuessCard({super.key, required this.reason, required this.selected, required this.child});
  final String reason;
  final bool selected;

  /// The result's own row (ResultTile).
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(2, 6, 2, 8),
      child: Semantics(
        container: true,
        label: 'Best guess. $reason',
        child: Glass(
          level: GlassLevel.card,
          radius: 18,
          fill: c.orangeA(c.isDark ? (selected ? .10 : .07) : (selected ? .08 : .05)),
          rim: c.orangeA(selected ? .7 : .38),
          padding: const EdgeInsets.fromLTRB(4, 8, 4, 2),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10),
                child: Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(color: c.orange, borderRadius: NbRadius.pillAll),
                      child: Text(
                        'Best guess',
                        style: NbType.text(NbSize.micro, c.onOrange, weight: FontWeight.w700, height: 1.3),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        reason,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: NbType.text(NbSize.micro, c.muted, weight: FontWeight.w600),
                      ),
                    ),
                    const Kbd('Enter'),
                    const SizedBox(width: 6),
                    Text('opens it', style: NbType.text(NbSize.micro, c.dim)),
                  ],
                ),
              ),
              const SizedBox(height: 2),
              child,
            ],
          ),
        ),
      ),
    );
  }
}
