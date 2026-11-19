/// Small shared pieces: the NOBAD mark, kind badges, previews, highlighted snippets, tail-cut paths.
library;

import 'dart:typed_data';

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import '../engine/engine_api.dart';
import '../engine/models/result.dart';

class NbMark extends StatelessWidget {
  const NbMark({super.key, this.size = 38});
  final double size;

  @override
  Widget build(BuildContext context) {
    final px = (size * MediaQuery.devicePixelRatioOf(context)).round();
    return Image.asset(
      'assets/nobad-mark.png',
      width: size,
      height: size,
      cacheWidth: px,
      cacheHeight: px,
      semanticLabel: 'NOBAD',
      filterQuality: FilterQuality.medium,
    );
  }
}

/// "PDF", "IMG", … in a small outlined square (app.css .ico).
class KindBadge extends StatelessWidget {
  const KindBadge(this.kind, {super.key, this.size = 40});
  final String kind;
  final double size;

  /// Small badges show the kind as a Windows icon; the large preview keeps the NOBAD kind tag.
  static const glyphs = {
    'pdf': 0xEA90,
    'document': 0xE8A5,
    'spreadsheet': 0xE80A,
    'slides': 0xE786,
    'text': 0xF000,
    'code': 0xE943,
    'email': 0xE715,
    'image': 0xE91B,
    'video': 0xE714,
    'audio': 0xE8D6,
    'archive': 0xF012,
    'ebook': 0xE8F1,
    'app': 0xE7B8,
    'folder': 0xE8B7,
  };

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final small = size <= 48;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: small ? c.cardHover : null,
        gradient: small
            ? null
            : LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [c.orangeA(c.isDark ? .12 : .08), c.card],
              ),
        border: Border.all(color: c.line),
        borderRadius: BorderRadius.circular(small ? 6 : 8),
      ),
      child: small
          ? ExcludeSemantics(
              child: Text(
                String.fromCharCode(glyphs[kind] ?? 0xE8A5),
                textScaler: TextScaler.noScaling,
                style: TextStyle(
                  fontFamily: 'Segoe Fluent Icons',
                  fontFamilyFallback: const ['Segoe MDL2 Assets'],
                  fontSize: 16,
                  height: 1,
                  color: kind == 'folder' ? c.orange : c.muted,
                ),
              ),
            )
          : Text(
              kindTag(kind),
              style: NbType.data(size >= 96 ? 24 : 16, c.orange, weight: FontWeight.w600),
              maxLines: 1,
              softWrap: false,
            ),
    );
  }
}

class ResultThumb extends StatefulWidget {
  const ResultThumb({super.key, required this.engine, required this.result, this.size = 56});
  final EngineApi engine;
  final FileResult result;
  final double size;

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
    final c = NbColors.of(context);
    final b = _bytes;
    final s = widget.size;
    if (b == null) {
      // big (the detail pane): the kind fills the frame; small: a badge at the top left of its slot
      return s >= 96
          ? KindBadge(widget.result.kind, size: s)
          : SizedBox(
              width: s,
              child: Align(alignment: Alignment.topLeft, child: KindBadge(widget.result.kind)),
            );
    }
    final px = (s * MediaQuery.devicePixelRatioOf(context)).round();
    return Container(
      width: s,
      height: s,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: c.shadow,
        border: Border.all(color: c.line),
        borderRadius: NbRadius.rowAll,
      ),
      child: Image.memory(
        b,
        fit: BoxFit.cover,
        cacheWidth: px,
        gaplessPlayback: true,
        errorBuilder: (_, _, _) => KindBadge(widget.result.kind),
      ),
    );
  }
}

/// The snippet with its matched words marked (\x02 … \x03 from the engine). Plain text spans only.
List<TextSpan> snippetSpans(String s, TextStyle base, NbColors c) {
  final out = <TextSpan>[];
  final mark = base.copyWith(color: c.text, backgroundColor: c.orangeA(c.isDark ? .25 : .16));
  var on = false;
  final buf = StringBuffer();
  void flush() {
    if (buf.isEmpty) return;
    out.add(TextSpan(text: buf.toString(), style: on ? mark : base));
    buf.clear();
  }

  var space = false, any = false;
  for (final ch in s.runes) {
    final ws = ch == 0x20 || ch == 0x09 || ch == 0x0A || ch == 0x0D;
    if (ws) {
      if (!space && any) buf.write(' ');
      space = true;
      continue;
    }
    space = false;
    if (ch != 2 && ch != 3) any = true;
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
/// bar's `direction: rtl` folders. Measured with a TextPainter; only used for short lists.
class TailText extends StatelessWidget {
  const TailText(this.text, {super.key, required this.style, this.textAlign = TextAlign.right});
  final String text;
  final TextStyle style;
  final TextAlign textAlign;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, c) {
      final scaler = MediaQuery.textScalerOf(context);
      // measured with the style the Text will really paint with (the inherited one merged in)
      final painted = DefaultTextStyle.of(context).style.merge(style);
      bool fits(String s) {
        final tp = TextPainter(
          text: TextSpan(text: s, style: painted),
          textDirection: TextDirection.ltr,
          maxLines: 1,
          textScaler: scaler,
        )..layout();
        final ok = tp.width <= c.maxWidth - 2; // a little room: the painted width can round up
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
      return Text(shown, style: style, maxLines: 1, softWrap: false, overflow: TextOverflow.clip, textAlign: textAlign);
    },
  );
}

/// [text] with the search's [terms] marked (case-insensitive), as plain text spans: names are never parsed.
List<TextSpan> highlightSpans(String text, List<String> terms, TextStyle base, NbColors c) {
  final words = [
    for (final t in terms)
      if (t.trim().length > 1) t.trim().toLowerCase(),
  ];
  if (words.isEmpty) return [TextSpan(text: text, style: base)];
  final lower = text.toLowerCase();
  final marks = List<bool>.filled(text.length, false);
  for (final w in words) {
    var i = lower.indexOf(w);
    while (i >= 0) {
      for (var k = i; k < i + w.length && k < marks.length; k++) {
        marks[k] = true;
      }
      i = lower.indexOf(w, i + w.length);
    }
  }
  final mark = base.copyWith(color: c.text, backgroundColor: c.orangeA(c.isDark ? .28 : .18));
  final out = <TextSpan>[];
  var start = 0;
  for (var i = 1; i <= text.length; i++) {
    if (i == text.length || marks[i] != marks[start]) {
      out.add(TextSpan(text: text.substring(start, i), style: marks[start] ? mark : base));
      start = i;
    }
  }
  return out;
}
