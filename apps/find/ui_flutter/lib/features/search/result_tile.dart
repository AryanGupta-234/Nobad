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

/// Shared by rows and cards: hover lift, click (Ctrl+click: show in folder), right-click, semantics.
class _CardShell extends StatelessWidget {
  const _CardShell({
    required this.result,
    required this.selected,
    required this.onTap,
    this.onSecondary,
    required this.builder,
    this.radius = 18,
    this.padding = const EdgeInsets.fromLTRB(16, 12, 16, 12),
  });
  final FileResult result;
  final bool selected;
  final void Function(bool reveal) onTap;
  final VoidCallback? onSecondary;
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
        onSecondaryTap: onSecondary,
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
  });

  final EngineApi engine;
  final FileResult result;
  final bool selected;

  /// [reveal] is true for Ctrl+click.
  final void Function(bool reveal) onTap;

  /// Right-click: show in folder (0.7.0).
  final VoidCallback? onSecondary;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final r = result;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: _CardShell(
        result: r,
        selected: selected,
        onTap: onTap,
        onSecondary: onSecondary,
        builder: (context, parallax, lit) => Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Transform.translate(
              offset: parallax,
              child: ResultThumb(engine: engine, result: r),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(r.name, style: NbType.text(15.5, c.text, weight: FontWeight.w600, height: 1.3)),
                  if (r.dir.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      // one line; a long folder keeps its end (the part that tells folders apart)
                      child: Tooltip(
                        message: r.dir,
                        waitDuration: const Duration(milliseconds: 700),
                        child: TailText(
                          r.dir,
                          textAlign: TextAlign.left,
                          style: NbType.data(NbSize.caption, c.dim, height: 1.35),
                        ),
                      ),
                    ),
                  if (r.snippet.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text.rich(
                        TextSpan(children: snippetSpans(r.snippet, NbType.text(13, c.muted, height: 1.55), c)),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  if (r.why.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 7),
                      child: Wrap(spacing: 5, runSpacing: 5, children: [for (final w in r.why) WhyChip(w)]),
                    ),
                ],
              ),
            ),
            const SizedBox(width: 14),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (r.ago.isNotEmpty)
                  Text(r.ago, style: NbType.data(NbSize.caption, lit ? c.muted : c.dim, height: 1.6)),
                if (humanSize(r.size).isNotEmpty)
                  Text(humanSize(r.size), style: NbType.data(NbSize.caption, c.dim, height: 1.6)),
              ],
            ),
          ],
        ),
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
  });
  final EngineApi engine;
  final FileResult result;
  final bool selected;
  final void Function(bool reveal) onTap;
  final VoidCallback? onSecondary;

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
      radius: 22,
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
  });
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
      radius: 28,
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
                padding: const EdgeInsets.all(22),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(
                      child: ResultThumb(engine: engine, result: r, size: 180),
                    ),
                    const SizedBox(height: 20),
                    Text(r.name, style: NbType.display(26, c.text, weight: 380)),
                    const SizedBox(height: 8),
                    SelectableText(r.dir, style: NbType.data(12, c.muted, height: 1.5)),
                    const SizedBox(height: 10),
                    Text(
                      [kindTag(r.kind), r.ago, humanSize(r.size)].where((s) => s.isNotEmpty).join('   '),
                      style: NbType.data(12, c.dim),
                    ),
                    if (r.snippet.isNotEmpty) ...[
                      const SizedBox(height: 16),
                      Text.rich(
                        TextSpan(children: snippetSpans(r.snippet, NbType.text(13.5, c.muted, height: 1.6), c)),
                      ),
                    ],
                    if (r.why.isNotEmpty) ...[
                      const SizedBox(height: 14),
                      Wrap(spacing: 6, runSpacing: 6, children: [for (final w in r.why) WhyChip(w)]),
                    ],
                    const SizedBox(height: 22),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        NbButton('Open', icon: NbGlyph.external, onPressed: onOpen),
                        NbButton('Show in folder', kind: NbButtonKind.ghost, icon: NbGlyph.folder, onPressed: onReveal),
                        NbButton('Copy path', kind: NbButtonKind.ghost, icon: NbGlyph.copy, onPressed: onCopy),
                        NbButton('Forget…', kind: NbButtonKind.quiet, onPressed: onForget),
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
      padding: const EdgeInsets.fromLTRB(6, 18, 6, 8),
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
