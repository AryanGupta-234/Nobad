/// One search result: preview or kind, name, folder, the words around the match, why it matched, age and size.
/// The selected row carries the signal: an orange bar at its left edge and a warm wash fading to the right.
library;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:material_ui/material_ui.dart' show Tooltip;

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../engine/models/result.dart';
import '../../widgets/common.dart';

class ResultTile extends StatefulWidget {
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
  State<ResultTile> createState() => _ResultTileState();
}

class _ResultTileState extends State<ResultTile> {
  var _hover = false;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final r = widget.result;
    final sel = widget.selected;
    final lit = sel || _hover;
    final d = NbMotion.of(context, NbMotion.base);
    Widget body = Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ResultThumb(engine: widget.engine, result: r),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(r.name, style: NbType.text(15, c.text, weight: FontWeight.w600, height: 1.3)),
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
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                if (r.why.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 7),
                    child: Wrap(spacing: 5, runSpacing: 5, children: [for (final w in r.why) _Why(w)]),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              if (r.ago.isNotEmpty) Text(r.ago, style: NbType.data(NbSize.caption, lit ? c.muted : c.dim, height: 1.6)),
              if (humanSize(r.size).isNotEmpty)
                Text(humanSize(r.size), style: NbType.data(NbSize.caption, c.dim, height: 1.6)),
            ],
          ),
        ],
      ),
    );
    Widget tile = AnimatedContainer(
      duration: d,
      curve: NbMotion.curve,
      decoration: BoxDecoration(
        borderRadius: NbRadius.rowAll,
        border: Border.all(color: sel ? c.orangeA(.45) : const Color(0x00000000)),
        // a flat tint (a faint gradient bands on light backgrounds)
        color: sel ? c.orangeA(c.isDark ? .09 : .06) : (_hover ? (c.isDark ? c.line : const Color(0x08000000)) : null),
      ),
      child: Stack(
        children: [
          body,
          Positioned(
            left: 0,
            top: 12,
            bottom: 12,
            child: AnimatedContainer(
              duration: d,
              curve: NbMotion.curve,
              width: sel ? 3 : 0,
              decoration: BoxDecoration(
                color: c.orange,
                borderRadius: const BorderRadius.horizontal(right: Radius.circular(3)),
              ),
            ),
          ),
        ],
      ),
    );
    if (r.weak && !lit) tile = Opacity(opacity: .62, child: tile);
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => widget.onTap(HardwareKeyboard.instance.isControlPressed),
        onSecondaryTap: widget.onSecondary,
        child: Semantics(selected: sel, button: true, label: r.name, child: tile),
      ),
    );
  }
}

class _Why extends StatelessWidget {
  const _Why(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
      decoration: BoxDecoration(
        border: Border.all(color: c.line2),
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
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 8),
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
