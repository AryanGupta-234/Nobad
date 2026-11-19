/// Results as glass: a row card (list), a tile card (grid), and the detail pane for the selected file.
///
/// A card rises on a spring when the pointer is over it and its preview leans toward the pointer. The selected one
/// is tinted warm with an orange rim. The detail pane shows the selected file large: preview, name, folder, why it
/// matched, and what can be done with it.
library;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:material_ui/material_ui.dart' show SelectableText, Tooltip;

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../engine/models/result.dart';
import '../../widgets/common.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/icons.dart';
import '../../widgets/motion.dart';
import 'result_actions.dart';

/// Shared by rows and cards: hover lift, click (Ctrl+click: show in folder), right-click, semantics.
class _CardShell extends StatelessWidget {
  const _CardShell({
    required this.result,
    required this.selected,
    required this.onTap,
    this.onSecondary,
    required this.builder,
    this.radius = 10,
    this.padding = const EdgeInsets.fromLTRB(12, 10, 12, 10),
  });
  final FileResult result;
  final bool selected;
  final void Function(bool reveal) onTap;
  final void Function(Offset globalPosition)? onSecondary;
  final Widget Function(BuildContext context, Offset parallax, bool lit) builder;
  final double radius;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget card = HoverLift(
      builder: (context, lift, parallax) => Glass(
        radius: radius,
        lift: selected ? 1 : lift,
        fill: selected ? c.orangeA(c.isDark ? .13 : .10) : (lift > .05 ? Color.lerp(c.card, c.cardHover, lift) : null),
        rim: selected ? c.orangeA(.55) : null,
        padding: padding,
        child: builder(context, parallax, selected || lift > .5),
      ),
    );
    if (result.weak && !selected) card = Opacity(opacity: .66, child: card);
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => onTap(HardwareKeyboard.instance.isControlPressed),
        onSecondaryTapDown: onSecondary == null ? null : (d) => onSecondary!(d.globalPosition),
        child: Semantics(selected: selected, button: true, label: result.name, child: card),
      ),
    );
  }
}

class ResultTile extends StatelessWidget {
  const ResultTile({
    super.key,
    required this.engine,
    required this.result,
    required this.selected,
    required this.onTap,
    this.onSecondary,
    this.onAction,
    this.terms = const [],
  });

  /// The search's words, marked in the name.
  final List<String> terms;
  final EngineApi engine;
  final FileResult result;
  final bool selected;

  /// [reveal] is true for Ctrl+click.
  final void Function(bool reveal) onTap;

  /// Right-click: the actions menu where the pointer is.
  final void Function(Offset globalPosition)? onSecondary;

  /// A button on the row (shown when it is selected or hovered); null: no buttons (the quick find bar).
  final void Function(ResultAction action)? onAction;

  /// A row: 56 px (name, then folder and the matching words on one line).
  static const height = 56.0;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final r = result;
    return _FlatRow(
      result: r,
      selected: selected,
      onTap: onTap,
      onSecondary: onSecondary,
      builder: (context, lit) => SizedBox(
        height: height - 1,
        child: Row(
          children: [
            ResultThumb(engine: engine, result: r, size: 32),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text.rich(
                    TextSpan(
                      children: highlightSpans(
                        r.name,
                        terms,
                        NbType.text(13.5, c.text, weight: FontWeight.w600, height: 1.3),
                        c,
                      ),
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 2),
                  // one line: the folder (its end, the part that tells folders apart), then the matching words
                  Row(
                    children: [
                      if (r.dir.isNotEmpty)
                        Flexible(
                          flex: r.snippet.isEmpty ? 1 : 2,
                          child: Tooltip(
                            message: r.dir,
                            waitDuration: const Duration(milliseconds: 700),
                            child: TailText(
                              r.dir,
                              textAlign: TextAlign.left,
                              style: NbType.data(11, c.dim, height: 1.3),
                            ),
                          ),
                        ),
                      if (r.snippet.isNotEmpty) ...[
                        if (r.dir.isNotEmpty) const SizedBox(width: 10),
                        Expanded(
                          flex: 3,
                          child: Text.rich(
                            TextSpan(children: snippetSpans(r.snippet, NbType.text(12, c.muted, height: 1.3), c)),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            // age and size; on the selected or hovered row the actions fade in in their place
            Stack(
              alignment: Alignment.centerRight,
              children: [
                AnimatedOpacity(
                  opacity: lit && onAction != null ? 0 : 1,
                  duration: NbMotion.of(context, NbMotion.fast),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      if (r.ago.isNotEmpty) Text(r.ago, style: NbType.data(11, lit ? c.muted : c.dim, height: 1.4)),
                      if (humanSize(r.size).isNotEmpty)
                        Text(humanSize(r.size), style: NbType.data(11, c.dim, height: 1.4)),
                    ],
                  ),
                ),
                if (onAction != null)
                  IgnorePointer(
                    ignoring: !lit,
                    child: AnimatedOpacity(
                      opacity: lit ? 1 : 0,
                      duration: NbMotion.of(context, NbMotion.fast),
                      child: InlineActions(compact: true, onAction: onAction!, onMore: (pos) => onSecondary?.call(pos)),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// A list row as in a command palette: flat on the list's panel, a 1 px line under it, a quiet lift when hovered
/// or selected, and the orange only in the small indicator of the selected one.
class _FlatRow extends StatefulWidget {
  const _FlatRow({
    required this.result,
    required this.selected,
    required this.onTap,
    required this.onSecondary,
    required this.builder,
  });
  final FileResult result;
  final bool selected;
  final void Function(bool reveal) onTap;
  final void Function(Offset globalPosition)? onSecondary;
  final Widget Function(BuildContext context, bool lit) builder;

  @override
  State<_FlatRow> createState() => _FlatRowState();
}

class _FlatRowState extends State<_FlatRow> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final sel = widget.selected;
    final lit = sel || _hover;
    Widget row = Container(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: c.line)),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: Stack(
        children: [
          Positioned.fill(
            top: 3,
            bottom: 3,
            child: AnimatedContainer(
              duration: NbMotion.of(context, NbMotion.fast),
              decoration: BoxDecoration(
                color: sel ? c.selected : (_hover ? c.cardHover : const Color(0x00000000)),
                borderRadius: NbRadius.rowAll,
              ),
            ),
          ),
          Positioned(
            left: 0,
            top: 18,
            bottom: 18,
            width: 3,
            child: AnimatedOpacity(
              opacity: sel ? 1 : 0,
              duration: NbMotion.of(context, NbMotion.fast),
              child: DecoratedBox(
                decoration: BoxDecoration(color: c.orange, borderRadius: const BorderRadius.all(Radius.circular(2))),
              ),
            ),
          ),
          Padding(padding: const EdgeInsets.fromLTRB(12, 0, 6, 0), child: widget.builder(context, lit)),
        ],
      ),
    );
    if (widget.result.weak && !sel) row = Opacity(opacity: .7, child: row);
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => widget.onTap(HardwareKeyboard.instance.isControlPressed),
        onSecondaryTapDown: widget.onSecondary == null ? null : (d) => widget.onSecondary!(d.globalPosition),
        child: Semantics(selected: sel, button: true, label: widget.result.name, child: row),
      ),
    );
  }
}

/// A result as a tile in the card grid: preview on top, name, folder, age and size.
class ResultCard extends StatelessWidget {
  const ResultCard({
    super.key,
    required this.engine,
    required this.result,
    required this.selected,
    required this.onTap,
    this.onSecondary,
    this.onAction,
  });
  final void Function(ResultAction action)? onAction;
  final EngineApi engine;
  final FileResult result;
  final bool selected;
  final void Function(bool reveal) onTap;
  final void Function(Offset globalPosition)? onSecondary;

  static const height = 214.0;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final r = result;
    return _CardShell(
      result: r,
      selected: selected,
      onTap: onTap,
      onSecondary: onSecondary,
      radius: 18,
      padding: const EdgeInsets.all(14),
      builder: (context, parallax, lit) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Transform.translate(
            offset: parallax * 1.6,
            child: ResultThumb(engine: engine, result: r, size: 96),
          ),
          const Spacer(),
          Text(
            r.name,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: NbType.text(14.5, c.text, weight: FontWeight.w600, height: 1.3),
          ),
          const SizedBox(height: 3),
          TailText(r.dir, textAlign: TextAlign.left, style: NbType.data(NbSize.micro + .5, c.dim, height: 1.4)),
          const SizedBox(height: 6),
          if (lit && onAction != null)
            InlineActions(compact: true, onAction: onAction!, onMore: (pos) => onSecondary?.call(pos))
          else
            Text(
              [r.ago, humanSize(r.size)].where((s) => s.isNotEmpty).join('   '),
              style: NbType.data(NbSize.micro + .5, lit ? c.muted : c.dim),
            ),
        ],
      ),
    );
  }
}

/// The selected file, large: a frosted pane with real blur behind it (one of the few blurred layers in the app).
class DetailPane extends StatelessWidget {
  const DetailPane({
    super.key,
    required this.engine,
    required this.result,
    required this.onOpen,
    required this.onReveal,
    required this.onCopy,
    required this.onForget,
    this.onOpenWith,
  });
  final VoidCallback? onOpenWith;
  final EngineApi engine;
  final FileResult? result;
  final VoidCallback onOpen;
  final VoidCallback onReveal;
  final VoidCallback onCopy;
  final VoidCallback onForget;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final r = result;
    return Glass(
      level: GlassLevel.panel,
      radius: 18,
      child: AnimatedSwitcher(
        duration: NbMotion.of(context, const Duration(milliseconds: 420)),
        switchInCurve: const SpringCurve(),
        layoutBuilder: (current, previous) => Stack(alignment: Alignment.topCenter, children: [...previous, ?current]),
        transitionBuilder: (child, a) => FadeTransition(
          opacity: a,
          child: ScaleTransition(
            scale: Tween(begin: .965, end: 1.0).animate(a),
            alignment: Alignment.topCenter,
            child: child,
          ),
        ),
        child: r == null
            ? Center(
                key: const ValueKey('none'),
                child: Text('Pick a result to see it here.', style: NbType.text(13.5, c.dim)),
              )
            : SingleChildScrollView(
                key: ValueKey(r.id),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(
                      child: ResultThumb(engine: engine, result: r, size: 132),
                    ),
                    const SizedBox(height: 14),
                    Text(r.name, style: NbType.text(15, c.text, weight: FontWeight.w600, height: 1.3)),
                    const SizedBox(height: 6),
                    SelectableText(r.dir, style: NbType.data(11.5, c.muted, height: 1.45)),
                    const SizedBox(height: 8),
                    Text(
                      [kindTag(r.kind), r.ago, humanSize(r.size)].where((s) => s.isNotEmpty).join('   '),
                      style: NbType.data(11.5, c.dim),
                    ),
                    if (r.snippet.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      Text.rich(
                        TextSpan(children: snippetSpans(r.snippet, NbType.text(12.5, c.muted, height: 1.5), c)),
                      ),
                    ],
                    if (r.why.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Wrap(spacing: 6, runSpacing: 6, children: [for (final w in r.why) WhyChip(w)]),
                    ],
                    const SizedBox(height: 16),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        NbButton('Open', small: true, icon: NbGlyph.external, onPressed: onOpen),
                        if (onOpenWith != null)
                          NbButton('Open with…', small: true, kind: NbButtonKind.ghost, onPressed: onOpenWith),
                        NbButton(
                          'Show in folder',
                          small: true,
                          kind: NbButtonKind.ghost,
                          icon: NbGlyph.folder,
                          onPressed: onReveal,
                        ),
                        NbButton(
                          'Copy path',
                          small: true,
                          kind: NbButtonKind.ghost,
                          icon: NbGlyph.copy,
                          onPressed: onCopy,
                        ),
                        NbButton('Forget…', small: true, kind: NbButtonKind.quiet, onPressed: onForget),
                      ],
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}

class WhyChip extends StatelessWidget {
  const WhyChip(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
      decoration: BoxDecoration(
        color: c.card,
        border: Border.all(color: c.line),
        borderRadius: NbRadius.pillAll,
      ),
      child: Text(text, style: NbType.text(NbSize.micro + .5, c.dim, height: 1.5)),
    );
  }
}

/// "Less sure" between the sure results and the weak ones.
class LessSure extends StatelessWidget {
  const LessSure({super.key});

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(6, 12, 6, 6),
      child: Row(
        children: [
          Text('Less sure', style: NbType.text(NbSize.small, c.dim, weight: FontWeight.w600)),
          const SizedBox(width: 12),
          Expanded(child: Container(height: 1, color: c.line)),
        ],
      ),
    );
  }
}
