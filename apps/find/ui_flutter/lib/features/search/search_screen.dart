/// Search: the box, the filter bar, what the question was understood as, the results (or Home), the status line.
///
/// Keys (0.7.0): ↑/↓ choose, Enter opens, Ctrl+Enter shows in folder, Ctrl+C copies the path (when no text is
/// selected in the box), Shift+Delete forgets, Esc clears the box and, when it's empty, hides the window.
library;

import 'dart:async';

import 'package:flutter/rendering.dart' show RenderAbstractViewport;
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart' show maxTextLength;
import '../../engine/events.dart';
import '../../engine/models/result.dart';
import '../../state/search_controller.dart';
import '../../platform/demo.dart';
import '../../widgets/dialogs.dart';
import '../../widgets/icons.dart';
import '../../widgets/motion.dart';
import '../../widgets/pressable.dart';
import 'filter_bar.dart';
import 'home_view.dart';
import 'result_tile.dart';
import 'status_line.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  late AppScope s;
  late final box = TextEditingController(text: AppScope.of(context).find.text);
  final focus = FocusNode(debugLabel: 'search box');
  final scroll = ScrollController();

  /// One key per row for the answer on screen, so the selected row can be scrolled to without rebuilding rows.
  final _rowKeys = <int, GlobalKey>{};
  int _keysFor = -1;
  StreamSubscription<EngineEvent>? _shows;
  int _lastSel = -1;
  bool _wired = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    s = AppScope.of(context);
    if (_wired) return;
    _wired = true;
    Demo.mainBox = box;
    box.addListener(() => s.find.setText(box.text));
    s.find.addListener(_follow);
    s.find.addListener(_takeHandOver);
    _takeHandOver();
    _shows = s.engine.events.listen((e) {
      if (e is ShowEvent && e.what == 'main' && e.text == null) {
        focus.requestFocus();
        box.selection = TextSelection(baseOffset: 0, extentOffset: box.text.length);
      }
    });
  }

  /// The bar's words (Alt+Enter), held by the controller until this screen is there to take them.
  void _takeHandOver() {
    final t = s.find.takeHandOver();
    if (t == null) return;
    box.text = t;
    box.selection = TextSelection.collapsed(offset: t.length);
    focus.requestFocus();
  }

  GlobalKey rowKey(int id) {
    if (_keysFor != s.find.serial) {
      _keysFor = s.find.serial;
      _rowKeys.clear();
    }
    return _rowKeys.putIfAbsent(id, GlobalKey.new);
  }

  void _follow() {
    if (s.find.selected == _lastSel) return;
    _lastSel = s.find.selected;
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(retry: true));
  }

  /// Scroll the selected row into view. Rows have different heights, so a row that isn't built yet (the selection
  /// jumped far, e.g. wrapping from the first to the last) is first reached by an estimate, then aligned.
  void _reveal({required bool retry}) {
    if (!mounted) return;
    final cur = s.find.current;
    final ctx = cur == null ? null : _rowKeys[cur.id]?.currentContext;
    if (ctx != null && ctx.mounted) {
      final ro = ctx.findRenderObject();
      final viewport = ro == null ? null : RenderAbstractViewport.maybeOf(ro);
      final above =
          viewport != null &&
          scroll.hasClients &&
          viewport.getOffsetToReveal(ro!, 0).offset < scroll.offset; // the row starts above the top edge
      Scrollable.ensureVisible(
        ctx,
        duration: NbMotion.of(context, NbMotion.fast),
        alignmentPolicy: s.find.selected == 0 || above
            ? ScrollPositionAlignmentPolicy.keepVisibleAtStart
            : ScrollPositionAlignmentPolicy.keepVisibleAtEnd,
      );
      return;
    }
    if (!retry || !scroll.hasClients || s.find.results.isEmpty) return;
    final p = scroll.position;
    p.jumpTo((p.maxScrollExtent * s.find.selected / s.find.results.length).clamp(0, p.maxScrollExtent));
    WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(retry: false));
    WidgetsBinding.instance.scheduleFrame();
  }

  @override
  void dispose() {
    if (identical(Demo.mainBox, box)) Demo.mainBox = null;
    _shows?.cancel();
    s.find.removeListener(_follow);
    s.find.removeListener(_takeHandOver);
    box.dispose();
    focus.dispose();
    scroll.dispose();
    super.dispose();
  }

  Future<void> _open({bool reveal = false}) async {
    if (reveal) {
      await s.find.revealSelected();
      return;
    }
    final ok = await s.find.openSelected();
    if (ok && s.settings.settings.flag('hide_after_open')) {
      s.window.hide();
      unawaited(s.engine.uiHidden('main').catchError((Object _) {}));
    }
  }

  void _copy() {
    final sel = box.selection;
    if (sel.isValid && !sel.isCollapsed) {
      // text selected in the box: a normal copy
      Clipboard.setData(ClipboardData(text: sel.textInside(box.text)));
      return;
    }
    unawaited(s.find.copySelected());
  }

  Future<void> _forget() async {
    await s.find.forgetSelected(
      (q) => confirmDialog(context, title: 'Forget this file?', question: q, yes: 'Forget', danger: true),
    );
    if (mounted) focus.requestFocus();
  }

  /// Esc clears the words, then the filters, and only then hides the window.
  void _escape() {
    if (box.text.isNotEmpty) {
      box.clear();
      return;
    }
    if (s.find.clearOne()) return;
    s.window.hide();
    unawaited(s.engine.uiHidden('main').catchError((Object _) {}));
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.arrowDown): () => s.find.move(1),
        const SingleActivator(LogicalKeyboardKey.arrowUp): () => s.find.move(-1),
        const SingleActivator(LogicalKeyboardKey.enter): _open,
        const SingleActivator(LogicalKeyboardKey.numpadEnter): _open,
        const SingleActivator(LogicalKeyboardKey.enter, control: true): () => _open(reveal: true),
        const SingleActivator(LogicalKeyboardKey.keyC, control: true): _copy,
        const SingleActivator(LogicalKeyboardKey.delete, shift: true): _forget,
        const SingleActivator(LogicalKeyboardKey.escape): _escape,
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(NbSpace.x6, NbSpace.x5, NbSpace.x6, NbSpace.x3),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _SearchBox(controller: box, focus: focus),
                const SizedBox(height: NbSpace.x3),
                FilterBar(onDone: focus.requestFocus),
              ],
            ),
          ),
          ListenableBuilder(
            listenable: s.find,
            builder: (context, _) => _Meta(find: s.find),
          ),
          Expanded(
            child: ListenableBuilder(
              listenable: s.find,
              builder: (context, _) => AnimatedSwitcher(
                duration: NbMotion.of(context, NbMotion.fast),
                child: s.find.showingResults && s.find.busy && s.find.results.isEmpty && s.find.notice.isEmpty
                    ? const Align(
                        key: ValueKey('loading'),
                        alignment: Alignment.topCenter,
                        child: Padding(
                          padding: EdgeInsets.symmetric(horizontal: NbSpace.x4),
                          child: SkeletonResults(),
                        ),
                      )
                    : !s.find.showingResults
                    ? HomeView(
                        key: const ValueKey('home'),
                        onExample: (t) {
                          box.text = t;
                          box.selection = TextSelection.collapsed(offset: t.length);
                          focus.requestFocus();
                        },
                        onTile: (words, f) {
                          s.find.setFilters(f);
                          box.text = words;
                          focus.requestFocus();
                        },
                      )
                    : _Results(
                        key: const ValueKey('results'),
                        scroll: scroll,
                        rowKey: rowKey,
                        onTap: (i, reveal) {
                          s.find.select(i);
                          _open(reveal: reveal);
                          focus.requestFocus();
                        },
                        onSecondary: (i) {
                          s.find.select(i);
                          _open(reveal: true);
                        },
                      ),
              ),
            ),
          ),
          Container(height: 1, color: c.line),
          const StatusLine(),
        ],
      ),
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
    final c = NbColors.of(context);
    final on = widget.focus.hasFocus;
    OutlineInputBorder border(Color col) => OutlineInputBorder(
      borderRadius: NbRadius.panelAll,
      borderSide: BorderSide(color: col),
    );
    return AnimatedContainer(
      duration: NbMotion.of(context, NbMotion.base),
      decoration: BoxDecoration(
        borderRadius: NbRadius.panelAll,
        boxShadow: [if (on) BoxShadow(color: c.orangeA(c.isDark ? .14 : .1), spreadRadius: 4)],
      ),
      child: TextField(
        controller: widget.controller,
        focusNode: widget.focus,
        autofocus: true,
        cursorColor: c.orange,
        inputFormatters: [LengthLimitingTextInputFormatter(maxTextLength)],
        style: NbType.text(NbSize.lead + 1, c.text),
        textInputAction: TextInputAction.search,
        decoration: InputDecoration(
          isDense: true,
          filled: true,
          fillColor: c.panel,
          hintText: 'Describe it: “rent pdf from last week”, “beach photos in march”, “budget.xlsx”',
          hintStyle: NbType.text(NbSize.lead + 1, c.dim),
          prefixIcon: Padding(
            padding: const EdgeInsets.only(left: 16, right: 10),
            child: NbIcon(NbGlyph.search, size: 20, color: on ? c.orange : c.dim),
          ),
          prefixIconConstraints: const BoxConstraints(minWidth: 46, minHeight: 20),
          // a way to clear the box with the mouse; Esc does the same
          suffixIcon: ListenableBuilder(
            listenable: widget.controller,
            builder: (context, _) => AnimatedOpacity(
              opacity: widget.controller.text.isEmpty ? 0 : 1,
              duration: NbMotion.of(context, NbMotion.fast),
              child: widget.controller.text.isEmpty
                  ? const SizedBox(width: 8)
                  : Padding(
                      padding: const EdgeInsets.only(right: 10),
                      child: Pressable(
                        onTap: () {
                          widget.controller.clear();
                          widget.focus.requestFocus();
                        },
                        semanticLabel: 'Clear',
                        tooltip: 'Clear (Esc)',
                        canRequestFocus: false,
                        ringRadius: NbRadius.pillAll,
                        builder: (context, p) => Container(
                          padding: const EdgeInsets.all(6),
                          decoration: BoxDecoration(color: p.lit ? c.line : null, shape: BoxShape.circle),
                          child: NbIcon(NbGlyph.close, size: 15, color: p.lit ? c.text : c.dim),
                        ),
                      ),
                    ),
            ),
          ),
          contentPadding: const EdgeInsets.fromLTRB(0, 17, 18, 17),
          enabledBorder: border(c.line2),
          focusedBorder: border(c.orangeA(.75)),
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
    final c = NbColors.of(context);
    final f = find;
    final a = f.answer;
    if (!f.showingResults) return const SizedBox(height: NbSpace.x1);
    final spans = <InlineSpan>[];
    if (f.notice.isNotEmpty) {
      spans.add(TextSpan(text: f.notice, style: NbType.text(NbSize.small, c.warn)));
    } else if (f.askedFor.isNotEmpty || f.filters.narrows) {
      spans.add(
        TextSpan(
          text: a.results.isEmpty
              ? 'Nothing found. Try fewer or other words, or fewer filters.'
              : '${a.results.length}${a.more ? '+' : ''} ${a.results.length == 1 && !a.more ? 'result' : 'results'} · ${a.ms} ms',
        ),
      );
      for (final n in a.notes) {
        spans.add(TextSpan(text: ' · $n', style: NbType.text(NbSize.small, c.warn)));
      }
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(NbSpace.x6 + 4, 0, NbSpace.x6, NbSpace.x2),
      child: Wrap(
        spacing: 6,
        runSpacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          for (final u in a.understood)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
              decoration: BoxDecoration(
                color: c.orangeA(.07),
                border: Border.all(color: c.orangeA(.5)),
                borderRadius: NbRadius.pillAll,
              ),
              child: Text(u, style: NbType.text(NbSize.small, c.orange, weight: FontWeight.w600, height: 1.3)),
            ),
          if (spans.isNotEmpty)
            Padding(
              padding: EdgeInsets.only(left: a.understood.isEmpty ? 0 : 6),
              child: Text.rich(TextSpan(children: spans), style: NbType.data(NbSize.caption, c.dim)),
            ),
        ],
      ),
    );
  }
}

class _Results extends StatelessWidget {
  const _Results({
    super.key,
    required this.scroll,
    required this.rowKey,
    required this.onTap,
    required this.onSecondary,
  });
  final ScrollController scroll;
  final GlobalKey Function(int id) rowKey;
  final void Function(int index, bool reveal) onTap;
  final void Function(int index) onSecondary;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final List<FileResult> rows = s.find.results;
    final firstWeak = rows.indexWhere((r) => r.weak);
    final divider = firstWeak > 0;
    return Scrollbar(
      controller: scroll,
      child: ListView.builder(
        controller: scroll,
        padding: const EdgeInsets.fromLTRB(NbSpace.x4, 0, NbSpace.x4, NbSpace.x6),
        itemCount: rows.length + (divider ? 1 : 0),
        itemBuilder: (context, i) {
          if (divider && i == firstWeak) return const LessSure();
          final idx = divider && i > firstWeak ? i - 1 : i;
          final sel = idx == s.find.selected;
          // each new answer comes in as a short cascade; moving the selection doesn't replay it
          return Appear(
            key: ValueKey((s.find.serial, rows[idx].id)),
            delay: Appear.stagger(i),
            child: ResultTile(
              key: rowKey(rows[idx].id), // stable: moving the selection only repaints two rows
              engine: s.engine,
              result: rows[idx],
              selected: sel,
              onTap: (reveal) => onTap(idx, reveal),
              onSecondary: () => onSecondary(idx),
            ),
          );
        },
      ),
    );
  }
}
