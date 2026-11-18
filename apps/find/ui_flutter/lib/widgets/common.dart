/// Small shared pieces: the NOBAD mark, kind badges, previews, key caps, highlighted snippets, tail-cut paths.
library;

import 'dart:typed_data';

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/typography.dart';
import '../engine/models/result.dart';
import '../engine/rpc.dart';

class NbMark extends StatelessWidget {
  const NbMark({super.key, this.size = 38});
  final double size;

  @override
  Widget build(BuildContext context) {
    final px = (size * MediaQuery.devicePixelRatioOf(context)).round();
    return Image.asset('assets/nobad-mark.png', width: size, height: size, cacheWidth: px, cacheHeight: px,
        semanticLabel: 'NOBAD', filterQuality: FilterQuality.medium);
  }
}

/// "PDF", "IMG", … in a small outlined square (app.css .ico).
class KindBadge extends StatelessWidget {
  const KindBadge(this.kind, {super.key, this.size = 38});
  final String kind;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(border: Border.all(color: Nb.line2), borderRadius: BorderRadius.circular(10)),
        child: Text(kindTag(kind),
            style: NbType.label(9.5, weight: FontWeight.w700, color: Nb.orange), maxLines: 1, softWrap: false),
      );
}

/// A result's preview from Windows' thumbnail cache, asked for (by id) only when the row is built, i.e. on screen.
/// Shows the kind badge until (and unless) a preview arrives.
class ResultThumb extends StatefulWidget {
  const ResultThumb({super.key, required this.engine, required this.result});
  final Engine engine;
  final FileResult result;

  @override
  State<ResultThumb> createState() => _ResultThumbState();
}

class _ResultThumbState extends State<ResultThumb> {
  Uint8List? _bytes;

  @override
  void initState() {
    super.initState();
    _ask();
  }

  @override
  void didUpdateWidget(ResultThumb old) {
    super.didUpdateWidget(old);
    if (old.result.id != widget.result.id) {
      _bytes = null;
      _ask();
    }
  }

  void _ask() {
    if (!widget.result.hasThumb) return;
    final id = widget.result.id;
    widget.engine.thumbnail(id).then((b) {
      if (mounted && b != null && widget.result.id == id) setState(() => _bytes = b);
    }, onError: (_) {});
  }

  @override
  Widget build(BuildContext context) {
    final b = _bytes;
    if (b == null) return KindBadge(widget.result.kind);
    final px = (64 * MediaQuery.devicePixelRatioOf(context)).round();
    return Container(
      width: 64,
      height: 64,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
          color: const Color(0xFF000000), border: Border.all(color: Nb.line), borderRadius: BorderRadius.circular(10)),
      child: Image.memory(b, fit: BoxFit.cover, cacheWidth: px, gaplessPlayback: true,
          errorBuilder: (_, _, _) => KindBadge(widget.result.kind)),
    );
  }
}

class Kbd extends StatelessWidget {
  const Kbd(this.label, {super.key});
  final String label;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(5),
          border: const Border(
              top: BorderSide(color: Nb.line2), left: BorderSide(color: Nb.line2), right: BorderSide(color: Nb.line2),
              bottom: BorderSide(color: Nb.line2, width: 2)),
        ),
        child: Text(label, style: NbType.label(10.5, color: Nb.text)),
      );
}

/// The snippet with its matched words marked (\x02 … \x03 from the engine). Plain text spans only.
List<TextSpan> snippetSpans(String s, TextStyle base) {
  final out = <TextSpan>[];
  final mark = base.copyWith(color: Nb.text, backgroundColor: Nb.orangeA(.25));
  var on = false;
  final buf = StringBuffer();
  void flush() {
    if (buf.isEmpty) return;
    out.add(TextSpan(text: buf.toString(), style: on ? mark : base));
    buf.clear();
  }

  for (final ch in s.runes) {
    if (ch == 2 || ch == 3) {
      flush();
      on = ch == 2;
    } else {
      buf.writeCharCode(ch);
    }
  }
  flush();
  return out;
}

/// One line of text that, when too long, keeps the end and cuts the start ("…\Projects\2026\tax"), like the
/// bar's `direction: rtl` folders. Measured with a TextPainter; only used for short lists (the bar's 8 rows).
class TailText extends StatelessWidget {
  const TailText(this.text, {super.key, required this.style, this.textAlign = TextAlign.right});
  final String text;
  final TextStyle style;
  final TextAlign textAlign;

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, c) {
        final scaler = MediaQuery.textScalerOf(context);
        bool fits(String s) {
          final tp = TextPainter(text: TextSpan(text: s, style: style), textDirection: TextDirection.ltr,
              maxLines: 1, textScaler: scaler)
            ..layout();
          final ok = tp.width <= c.maxWidth;
          tp.dispose();
          return ok;
        }

        var shown = text;
        if (c.maxWidth.isFinite && !fits(text)) {
          var lo = 0, hi = text.length; // keep text.substring(i) for the smallest i that fits
          while (lo < hi) {
            final mid = (lo + hi) ~/ 2;
            if (fits('…${text.substring(mid)}')) {
              hi = mid;
            } else {
              lo = mid + 1;
            }
          }
          if (lo < text.length && (text.codeUnitAt(lo) & 0xFC00) == 0xDC00) lo++; // never half a character
          shown = '…${text.substring(lo)}';
        }
        return Text(shown, style: style, maxLines: 1, softWrap: false, overflow: TextOverflow.clip,
            textAlign: textAlign);
      });
}
