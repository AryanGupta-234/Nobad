/// One row of the search results (app.css .res): preview or kind, name, folder, snippet, why chips, age and size.
library;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/result.dart';
import '../../engine/rpc.dart';
import '../../widgets/common.dart';

class ResultTile extends StatefulWidget {
  const ResultTile({
    super.key,
    required this.engine,
    required this.result,
    required this.selected,
    required this.onTap,
  });

  final Engine engine;
  final FileResult result;
  final bool selected;

  /// [reveal] is true for Ctrl+click.
  final void Function(bool reveal) onTap;

  @override
  State<ResultTile> createState() => _ResultTileState();
}

class _ResultTileState extends State<ResultTile> {
  var _hover = false;

  @override
  Widget build(BuildContext context) {
    final r = widget.result;
    final lit = widget.selected || _hover;
    final side = [r.ago, humanSize(r.size)].where((s) => s.isNotEmpty).join('\n');
    Widget tile = AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOutCubic,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: widget.selected ? Nb.orangeA(.5) : const Color(0x00000000)),
        gradient: LinearGradient(
          colors: [Nb.orangeA(lit ? .14 : 0), Nb.orangeA(0)],
          stops: const [0, .7],
        ),
      ),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        ResultThumb(engine: widget.engine, result: r),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(r.name, style: NbType.text(15, weight: FontWeight.w600)),
            if (r.dir.isNotEmpty) Text(r.dir, style: NbType.label(11.5)),
            if (r.snippet.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text.rich(TextSpan(children: snippetSpans(r.snippet, NbType.text(13, color: Nb.muted, height: 1.55))),
                    maxLines: 3, overflow: TextOverflow.ellipsis),
              ),
            if (r.why.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Wrap(spacing: 5, runSpacing: 5, children: [for (final w in r.why) _Why(w)]),
              ),
          ]),
        ),
        if (side.isNotEmpty) ...[
          const SizedBox(width: 12),
          Text(side, textAlign: TextAlign.right, style: NbType.label(11, height: 1.6)),
        ],
      ]),
    );
    if (r.weak && !lit) tile = Opacity(opacity: .62, child: tile);
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => widget.onTap(HardwareKeyboard.instance.isControlPressed),
        child: Semantics(selected: widget.selected, button: true, label: r.name, child: tile),
      ),
    );
  }
}

class _Why extends StatelessWidget {
  const _Why(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(border: Border.all(color: Nb.line2), borderRadius: BorderRadius.circular(999)),
        child: Text(text, style: NbType.label(10, height: 1.5)),
      );
}

/// "Less sure" between the sure results and the weak ones.
class LessSure extends StatelessWidget {
  const LessSure({super.key});

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.fromLTRB(4, 14, 4, 6),
        padding: const EdgeInsets.only(top: 10),
        decoration: const BoxDecoration(border: Border(top: BorderSide(color: Nb.line))),
        child: Text('LESS SURE', style: NbType.label(10, weight: FontWeight.w700, spacing: .8)),
      );
}
