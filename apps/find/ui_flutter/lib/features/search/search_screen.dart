/// The main window's search screen: rail, search box, what the question was understood as, results, status line.
library;

import 'dart:async';

import 'package:flutter/rendering.dart' show RenderAbstractViewport;
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/typography.dart';
import '../../engine/events.dart';
import '../../engine/rpc.dart';
import '../../platform/demo.dart';
import '../../platform/window.dart';
import '../../state/search_controller.dart';
import '../../state/status_controller.dart';
import '../../widgets/common.dart';
import 'result_tile.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key, required this.engine, this.window = const NoWindow(), this.version = '', this.demo});
  final Engine engine;
  final Demo? demo;
  final WindowControl window;
  final String version;

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  late final FindController find = FindController(widget.engine);
  late final StatusController status = StatusController(widget.engine);
  final box = TextEditingController();
  final focus = FocusNode(debugLabel: 'search box');
  final scroll = ScrollController();
  final _selKey = GlobalKey();
  late final StreamSubscription<EngineEvent> _shows;
  int _lastSel = -1;

  @override
  void initState() {
    super.initState();
    box.addListener(() => find.setText(box.text));
    find.addListener(_follow);
    _shows = widget.engine.events.listen((e) {
      if (e is ShowEvent && e.what == 'main') {
        widget.window.front();
        focus.requestFocus();
        box.selection = TextSelection(baseOffset: 0, extentOffset: box.text.length);
      }
    });
    widget.demo?.run(widget.engine, box, find, 'main');
  }

  void _follow() {
    if (find.selected == _lastSel) return;
    _lastSel = find.selected;
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(retry: true));
  }

  /// Scroll the selected row into view. Rows have different heights, so a row that isn't built yet (the selection
  /// jumped far, e.g. wrapping from the first to the last) is first reached by an estimate, then aligned.
  void _reveal({required bool retry}) {
    if (!mounted) return;
    final ctx = _selKey.currentContext;
    if (ctx != null && ctx.mounted) {
      final ro = ctx.findRenderObject();
      final viewport = ro == null ? null : RenderAbstractViewport.maybeOf(ro);
      final above = viewport != null && scroll.hasClients &&
          viewport.getOffsetToReveal(ro!, 0).offset < scroll.offset; // the row starts above the top edge
      Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 120),
          alignmentPolicy: find.selected == 0 || above
              ? ScrollPositionAlignmentPolicy.keepVisibleAtStart
              : ScrollPositionAlignmentPolicy.keepVisibleAtEnd);
      return;
    }
    if (!retry || !scroll.hasClients || find.results.isEmpty) return;
    final p = scroll.position;
    p.jumpTo((p.maxScrollExtent * find.selected / find.results.length).clamp(0, p.maxScrollExtent));
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(retry: false));
    WidgetsBinding.instance.scheduleFrame();
  }

  @override
  void dispose() {
    _shows.cancel();
    find.dispose();
    status.dispose();
    box.dispose();
    focus.dispose();
    scroll.dispose();
    super.dispose();
  }

  void _open({bool reveal = false}) => reveal ? find.revealSelected() : find.openSelected();

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Nb.bg,
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _Rail(status: status, version: widget.version),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(28, 22, 28, 0),
              child: CallbackShortcuts(
                bindings: {
                  const SingleActivator(LogicalKeyboardKey.arrowDown): () => find.move(1),
                  const SingleActivator(LogicalKeyboardKey.arrowUp): () => find.move(-1),
                  const SingleActivator(LogicalKeyboardKey.enter): _open,
                  const SingleActivator(LogicalKeyboardKey.numpadEnter): _open,
                  const SingleActivator(LogicalKeyboardKey.enter, control: true): () => _open(reveal: true),
                  const SingleActivator(LogicalKeyboardKey.escape): box.clear,
                },
                child: _SearchBox(controller: box, focus: focus),
              ),
            ),
            ListenableBuilder(listenable: find, builder: (context, _) => _Meta(find: find)),
            Expanded(
              child: ListenableBuilder(
                listenable: find,
                builder: (context, _) => find.text.trim().isEmpty
                    ? const _Home()
                    : _Results(find: find, engine: widget.engine, scroll: scroll, selKey: _selKey,
                        onTap: (i, reveal) {
                          find.select(i);
                          _open(reveal: reveal);
                          focus.requestFocus();
                        }),
              ),
            ),
            ListenableBuilder(listenable: status, builder: (context, _) => _StatusLine(status: status)),
          ]),
        ),
      ]),
    );
  }
}

class _SearchBox extends StatefulWidget {
  const _SearchBox({required this.controller, required this.focus});
  final TextEditingController controller;
  final FocusNode focus;

  @override
  State<_SearchBox> createState() => _SearchBoxState();
}

class _SearchBoxState extends State<_SearchBox> {
  @override
  void initState() {
    super.initState();
    widget.focus.addListener(_changed);
  }

  void _changed() => setState(() {});

  @override
  void dispose() {
    widget.focus.removeListener(_changed);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final on = widget.focus.hasFocus;
    OutlineInputBorder border(Color c) =>
        OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide(color: c));
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        boxShadow: [if (on) BoxShadow(color: Nb.orangeA(.12), spreadRadius: 4)],
      ),
      child: TextField(
        controller: widget.controller,
        focusNode: widget.focus,
        autofocus: true,
        cursorColor: Nb.orange,
        style: NbType.text(18),
        textInputAction: TextInputAction.search,
        decoration: InputDecoration(
          isDense: true,
          filled: true,
          fillColor: Nb.bg2,
          hintText: 'Describe it: “rent pdf from last week”, “beach photos in march”, “budget.xlsx”',
          hintStyle: NbType.text(18, color: Nb.dim),
          contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
          enabledBorder: border(Nb.line2),
          focusedBorder: border(Nb.orangeA(.7)),
        ),
      ),
    );
  }
}

class _Meta extends StatelessWidget {
  const _Meta({required this.find});
  final FindController find;

  @override
  Widget build(BuildContext context) {
    final a = find.answer;
    final q = find.text.trim();
    final chips = [
      for (final u in a.understood)
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: Nb.orangeA(.07),
            border: Border.all(color: Nb.orangeA(.5)),
            borderRadius: BorderRadius.circular(999),
          ),
          child: Text(u.toUpperCase(), style: NbType.label(10.5, weight: FontWeight.w700, color: Nb.orange, spacing: .6)),
        ),
    ];
    final spans = <InlineSpan>[];
    if (q.isNotEmpty && find.askedFor.isNotEmpty) {
      if (find.notice.isNotEmpty) {
        spans.add(TextSpan(text: find.notice, style: NbType.text(12, color: Nb.warn)));
      } else {
        spans.add(TextSpan(
            text: a.results.isEmpty
                ? 'Nothing found. Try fewer or other words, or fewer filters.'
                : '${a.results.length}${a.more ? '+' : ''} results · ${a.ms} ms'));
        for (final n in a.notes) {
          spans.add(TextSpan(text: ' · $n', style: NbType.text(12, color: Nb.warn)));
        }
      }
    } else if (q.isNotEmpty && find.notice.isNotEmpty) {
      spans.add(TextSpan(text: find.notice, style: NbType.text(12, color: Nb.warn)));
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(30, 8, 30, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (chips.isNotEmpty) Padding(padding: const EdgeInsets.only(bottom: 8), child: Wrap(spacing: 6, runSpacing: 6, children: chips)),
        Text.rich(TextSpan(children: spans), style: NbType.label(11)),
      ]),
    );
  }
}

class _Results extends StatelessWidget {
  const _Results({required this.find, required this.engine, required this.scroll, required this.selKey,
      required this.onTap});
  final FindController find;
  final Engine engine;
  final ScrollController scroll;
  final GlobalKey selKey;
  final void Function(int index, bool reveal) onTap;

  @override
  Widget build(BuildContext context) {
    final rows = find.results;
    final firstWeak = rows.indexWhere((r) => r.weak);
    final divider = firstWeak > 0;
    return ListView.builder(
      controller: scroll,
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
      itemCount: rows.length + (divider ? 1 : 0),
      itemBuilder: (context, i) {
        if (divider && i == firstWeak) return const LessSure();
        final idx = divider && i > firstWeak ? i - 1 : i;
        final sel = idx == find.selected;
        return ResultTile(
          key: sel ? selKey : ValueKey(rows[idx].id),
          engine: engine,
          result: rows[idx],
          selected: sel,
          onTap: (reveal) => onTap(idx, reveal),
        );
      },
    );
  }
}

class _Home extends StatelessWidget {
  const _Home();

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(30, 36, 30, 28),
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 780),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('FIND ANYTHING ON THIS PC.', style: NbType.heading(40)),
              const SizedBox(height: 16),
              Container(width: 46, height: 3, decoration: BoxDecoration(color: Nb.orange,
                  boxShadow: [BoxShadow(color: Nb.orange, blurRadius: 16)])),
              const SizedBox(height: 16),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 560),
                child: Text(
                    'Search by name, by the words inside a file, or by what it was about. Add a kind, a time, a '
                    'folder or a size to the words.',
                    style: NbType.text(14, color: Nb.muted, height: 1.5)),
              ),
              const SizedBox(height: 22),
              Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 6, runSpacing: 8, children: [
                const Kbd('↑'), const Kbd('↓'), Text('choose  ', style: NbType.label(11)),
                const Kbd('Enter'), Text('opens  ', style: NbType.label(11)),
                const Kbd('Ctrl+Enter'), Text('shows in folder  ', style: NbType.label(11)),
                const Kbd('Esc'), Text('clears', style: NbType.label(11)),
              ]),
            ]),
          ),
        ),
      );
}

class _Rail extends StatelessWidget {
  const _Rail({required this.status, required this.version});
  final StatusController status;
  final String version;

  @override
  Widget build(BuildContext context) => Container(
        width: 92,
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 8),
        decoration: const BoxDecoration(color: Nb.bg2, border: Border(right: BorderSide(color: Nb.line))),
        child: Column(children: [
          const NbMark(size: 38),
          const SizedBox(height: 20),
          Container(
            width: 72,
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
            decoration: BoxDecoration(
              color: Nb.orangeA(.08),
              border: Border.all(color: Nb.orangeA(.45)),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(children: [
              Text('⌕', style: NbType.text(18, color: Nb.orange, height: 1.2)),
              Text('SEARCH', style: NbType.label(10, weight: FontWeight.w700, color: Nb.orange, spacing: .8)),
            ]),
          ),
          const Spacer(),
          ListenableBuilder(
            listenable: status,
            builder: (context, _) => Text(
              (status.link == Link.connected ? (status.status?.phaseLabel ?? '') : 'offline').toUpperCase(),
              textAlign: TextAlign.center,
              style: NbType.label(10, spacing: .6, height: 1.4),
            ),
          ),
          if (version.isNotEmpty) Text(version, style: NbType.label(9.5, height: 1.6)),
        ]),
      );
}

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.status});
  final StatusController status;

  @override
  Widget build(BuildContext context) {
    final s = status.status;
    final ok = status.link == Link.connected;
    final reason = ok ? (s?.reason ?? '') : '';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 9),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: Nb.line))),
      child: Row(children: [
        Container(
          width: 7,
          height: 7,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: ok && s?.level != 'paused' ? Nb.orange : Nb.dim,
            boxShadow: [if (ok) BoxShadow(color: Nb.orangeA(.6), blurRadius: 8)],
          ),
        ),
        const SizedBox(width: 10),
        Flexible(child: Text(status.line, style: NbType.label(12, color: Nb.muted), maxLines: 1,
            overflow: TextOverflow.ellipsis)),
        if (reason.isNotEmpty) ...[
          const SizedBox(width: 14),
          Expanded(child: Text(reason, style: NbType.label(11), maxLines: 1, overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.right)),
        ] else
          const Spacer(),
      ]),
    );
  }
}
