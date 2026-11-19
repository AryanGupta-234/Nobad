/// The quick find bar (`--bar`): frameless, on top, 640 px wide, a third of the way down the monitor with the
/// mouse; at most 8 rows tall, scrolling through every result the engine sends (the less sure ones too, under
/// "Less sure"); Enter opens, Ctrl+Enter shows in folder, Alt+Enter hands the words to the main window,
/// Esc hides. The engine's bar hotkey shows it.
///
/// 0.8.5 smart search, as in the main window: the understood parts as removable chips (the bar's filters), up to 3
/// suggestions above the results (↑ from the first result goes up into them, Enter takes one), the dim inline
/// completion (Tab or → takes it), the best guess marked on the first row (Enter opens it), and when there are more
/// results than fit, a last line "N results · Alt+Enter opens them in NOBAD Find".
library;

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../engine/events.dart';
import '../../engine/models/result.dart';
import '../../platform/demo.dart';
import '../../platform/window.dart';
import '../../state/search_controller.dart';
import '../../widgets/common.dart';
import '../../widgets/pressable.dart';
import '../search/result_actions.dart';
import '../search/smart_search.dart';
import '../../state/suggest_controller.dart';
import '../../widgets/glass.dart';
import '../../widgets/motion.dart';

class BarWindow extends StatefulWidget {
  const BarWindow({super.key, required this.engine, this.window = const NoWindow(), this.demo});
  final EngineApi engine;
  final Demo? demo;
  final WindowControl window;

  @override
  State<BarWindow> createState() => _BarWindowState();
}

class _BarWindowState extends State<BarWindow> {
  // every result the engine sends (no cut to the window's rows): the list scrolls
  late final FindController find = FindController(widget.engine, debounce: const Duration(milliseconds: 90));
  final scroll = ScrollController();
  int _followed = -1;
  final box = GhostTextController();
  late final SuggestController sug = SuggestController(widget.engine, channel: 'bar');
  final focus = FocusNode(debugLabel: 'bar box');

  /// Suggestion rows shown above the results (the bar's window only has room for 8 rows in all).
  static const maxSuggestions = 3;
  bool _quiet = false;
  late final StreamSubscription<EngineEvent> _shows;
  int _rows = -1;

  @override
  void initState() {
    super.initState();
    box.addListener(() {
      final changed = box.text != find.text;
      find.setText(box.text);
      if (changed && !_quiet) sug.typed(box.text);
      box.ghost = sug.ghostFor(box.text);
    });
    sug.addListener(() {
      box.ghost = sug.ghostFor(box.text);
      _fit();
    });
    find.addListener(() => sug.exclude = {for (final r in find.results.take(BarSize.maxRows)) r.id});
    find.addListener(_fit);
    find.addListener(_follow);
    _shows = widget.engine.events.listen((e) {
      if (e is ShowEvent && e.what == 'bar') show();
      if (e is QuittingEvent) widget.window.close();
    });
    widget.demo?.run(widget.engine, box, find, 'bar', after: hide);
    _life; // start listening
  }

  /// The understood parts' line (the bar's filters), while there's an answer that has them.
  int get chipRows => find.askedFor.isNotEmpty && find.text.trim().isNotEmpty && find.answer.parts.isNotEmpty ? 1 : 0;

  /// Suggestion rows on show now (always leaving a row for the results).
  int get suggestionRows => sug.isOpen && find.text.trim().isNotEmpty
      ? sug.items.length.clamp(0, maxSuggestions).clamp(0, BarSize.maxRows - 1 - chipRows)
      : 0;

  /// The result list's lines: a result's index, or -1 for the "Less sure" line before the first loose match.
  List<int> get listItems {
    final firstWeak = find.results.indexWhere((r) => r.weak);
    return [
      for (var i = 0; i < find.results.length; i++) ...[if (i == firstWeak && firstWeak > 0) -1, i],
    ];
  }

  /// More lines than the window has room for: the list scrolls and the last line says how many there are.
  bool get overflows => chipRows + suggestionRows + listItems.length > BarSize.maxRows;

  /// Rows the window needs: chips, suggestions and results (and the count line), or one for "No match for …".
  int get rowsNeeded {
    if (find.text.trim().isEmpty) return 0;
    final ns = suggestionRows;
    if (find.askedFor.isEmpty) return ns;
    if (find.results.isEmpty) return chipRows + ns + 1;
    return overflows ? BarSize.maxRows : chipRows + ns + listItems.length;
  }

  /// ↑/↓ moved the selection: scroll the list so the selected row is in view (every row is BarSize.row tall).
  void _follow() {
    if (find.selected == _followed) return;
    _followed = find.selected;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !scroll.hasClients) return;
      final at = listItems.indexOf(find.selected);
      if (at < 0) return;
      final row = BarSize.row.toDouble();
      final p = scroll.position;
      final top = at * row - (at > 0 && listItems[at - 1] == -1 ? row : 0); // keep "Less sure" above its first row
      if (top < p.pixels) {
        p.jumpTo(top.clamp(0, p.maxScrollExtent));
      } else if ((at + 1) * row > p.pixels + p.viewportDimension) {
        p.jumpTo(((at + 1) * row - p.viewportDimension).clamp(0, p.maxScrollExtent));
      }
    });
  }

  /// A chip's x: search the question without that part.
  void _words(String t) {
    _quiet = true;
    box.value = TextEditingValue(
      text: t,
      selection: TextSelection.collapsed(offset: t.length),
    );
    _quiet = false;
    sug.close();
    focus.requestFocus();
  }

  void _down() {
    if (sug.down(noResults: find.results.isEmpty)) return;
    find.move(1);
  }

  void _up() {
    if (sug.up(atTop: find.results.isEmpty || find.selected == 0)) return;
    find.move(-1);
  }

  void _enter() {
    final x = sug.current;
    if (x == null) {
      sug.close();
      unawaited(_act());
      return;
    }
    _quiet = true;
    box.value = TextEditingValue(
      text: x.text,
      selection: TextSelection.collapsed(offset: x.text.length),
    );
    _quiet = false;
    sug.close();
    find.remember(x.text);
  }

  void _escape() {
    if (sug.close()) return;
    hide();
  }

  /// Tab, or → with the caret at the end: the inline completion.
  KeyEventResult _ghostKeys(FocusNode node, KeyEvent e) {
    if (e is KeyDownEvent &&
        (e.logicalKey == LogicalKeyboardKey.tab ||
            e.logicalKey == LogicalKeyboardKey.arrowRight && box.atEnd && box.ghost.isNotEmpty) &&
        box.acceptGhost()) {
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  void _fit() {
    final n = rowsNeeded;
    if (n != _rows) {
      _rows = n;
      widget.window.fitBar(n);
    }
  }

  /// The bar's content opens with a quick fade and settle, and fades before the window hides.
  bool _open = true;
  Timer? _hiding;

  /// On screen, and since when (the focus shuffles for a moment while the window comes up).
  bool _visible = true;
  bool _settling = false;
  Timer? _settle;
  late final AppLifecycleListener _life = AppLifecycleListener(
    onInactive: () {
      if (_visible && !_settling) hide();
    },
  );

  // ---- menus: the n mark's app menu, and a result's actions ----
  final _menu = MenuController();
  final _menuAnchor = GlobalKey();
  List<Widget> _menuItems = const [];

  void _openMenu(List<Widget> items, Offset global) {
    final box = _menuAnchor.currentContext?.findRenderObject() as RenderBox?;
    setState(() => _menuItems = items);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (box != null && mounted) _menu.open(position: box.globalToLocal(global));
    });
  }

  Future<void> _rowAction(ResultAction a) async {
    final ok = switch (a) {
      ResultAction.open => await find.openSelected(),
      ResultAction.openWith => await find.openWithSelected(),
      ResultAction.reveal => await find.revealSelected(),
      ResultAction.copyPath => await find.copySelected(),
      ResultAction.copyName => await find.copyNameSelected(),
      ResultAction.details || ResultAction.forget => false,
    };
    if (ok && (a == ResultAction.open || a == ResultAction.openWith || a == ResultAction.reveal)) hide();
    if (mounted) setState(() {});
  }

  MenuItemButton _item(String label, VoidCallback onPressed, {SingleActivator? shortcut}) => MenuItemButton(
    onPressed: onPressed,
    shortcut: shortcut,
    child: Text(label, style: NbType.text(13, NbColors.of(context).text)),
  );

  List<Widget> _rowMenu() => [
    for (final a in [ResultAction.open, ResultAction.openWith, ResultAction.reveal, ResultAction.copyPath])
      _item(a.label, () => _rowAction(a), shortcut: a.shortcut),
  ];

  List<Widget> _appMenu() {
    final paused = widget.engine.lastStatus?.isPaused ?? false;
    return [
      _item('Open NOBAD Find', () {
        unawaited(widget.engine.toMain(box.text).catchError((Object _) {}));
        hide();
      }),
      _item('Settings', () => _openPage('settings')),
      _item('Index', () => _openPage('index')),
      _item(paused ? 'Resume' : 'Pause for 1 hour', () {
        final f = paused ? widget.engine.resume() : widget.engine.pauseFor(const Duration(hours: 1));
        unawaited(f.then((_) {}, onError: (Object _) {}));
      }),
      _item('Quit NOBAD Find', () => unawaited(widget.engine.quit().then((_) {}, onError: (Object _) {}))),
    ];
  }

  /// Settings or Index from the bar: starts the main window on that page (`--page`). If the main window already
  /// runs, Windows brings it forward on the page it shows (the engine has no "show this page" method yet).
  void _openPage(String page) {
    hide();
    openMainPage(page);
  }

  void show() {
    _hiding?.cancel();
    _visible = true;
    _settling = true;
    _settle?.cancel();
    _settle = Timer(const Duration(milliseconds: 400), () => _settling = false);
    _quiet = true;
    box.clear();
    _quiet = false;
    sug.close();
    setState(() => _open = false);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) setState(() => _open = true);
    });

    _rows = -1;
    widget.window.showBar();
    _fit();
    focus.requestFocus();
    unawaited(widget.engine.uiShown('bar').catchError((Object _) {}));
  }

  void hide() {
    _visible = false;
    unawaited(widget.engine.uiHidden('bar').catchError((Object _) {}));
    if (MediaQuery.maybeDisableAnimationsOf(context) ?? false) return _gone();
    setState(() => _open = false);
    _hiding?.cancel();
    _hiding = Timer(const Duration(milliseconds: 110), _gone);
  }

  void _gone() {
    widget.window.hide();
    _quiet = true;
    box.clear();
    _quiet = false;
    sug.close();
    if (mounted) setState(() => _open = true);
  }

  Future<void> _act({bool reveal = false}) async {
    final ok = reveal ? await find.revealSelected() : await find.openSelected();
    if (ok) {
      hide();
    } else {
      setState(() {});
    }
  }

  Future<void> _toMain() async {
    final words = box.text;
    try {
      await widget.engine.toMain(words);
    } on Object {
      return;
    }
    hide();
  }

  @override
  void dispose() {
    _shows.cancel();
    _hiding?.cancel();
    _menu.close();
    _life.dispose();
    _settle?.cancel();
    find.dispose();
    scroll.dispose();
    sug.dispose();
    box.dispose();
    focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final d = NbMotion.of(context, const Duration(milliseconds: 140));
    return AnimatedOpacity(
      opacity: _open ? 1 : 0,
      duration: d,
      child: AnimatedScale(scale: _open ? 1 : .985, duration: d, curve: NbMotion.curve, child: _frame(c)),
    );
  }

  Widget _frame(NbColors c) {
    // a frosted pill: Windows' Acrylic behind the window does the blur; the glass adds the tint and the rim
    return Glass(
      level: GlassLevel.panel,
      radius: 18,
      fill: c.glass ? c.panel : c.surface,
      child: MenuAnchor(
        controller: _menu,
        menuChildren: _menuItems,
        onOpen: () => widget.window.fitBar(BarSize.maxRows), // room for the menu inside the bar's window
        onClose: () {
          _rows = -1;
          _fit();
        },
        child: KeyedSubtree(
          key: _menuAnchor,
          child: CallbackShortcuts(
            bindings: {
              const SingleActivator(LogicalKeyboardKey.enter, control: true, shift: true): () =>
                  _rowAction(ResultAction.openWith),
              const SingleActivator(LogicalKeyboardKey.arrowDown): _down,
              const SingleActivator(LogicalKeyboardKey.arrowUp): _up,
              const SingleActivator(LogicalKeyboardKey.enter): _enter,
              const SingleActivator(LogicalKeyboardKey.numpadEnter): _enter,
              const SingleActivator(LogicalKeyboardKey.enter, control: true): () => _act(reveal: true),
              const SingleActivator(LogicalKeyboardKey.enter, alt: true): _toMain,
              const SingleActivator(LogicalKeyboardKey.escape): _escape,
            },
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(
                  height: BarSize.field - 2,
                  child: Focus(
                    canRequestFocus: false,
                    skipTraversal: true,
                    onKeyEvent: _ghostKeys,
                    child: _Field(box: box, focus: focus, find: find, onMark: (pos) => _openMenu(_appMenu(), pos)),
                  ),
                ),
                Expanded(
                  child: ListenableBuilder(
                    listenable: Listenable.merge([find, sug]),
                    builder: (context, _) {
                      if (rowsNeeded == 0) return const SizedBox.shrink();
                      final ns = suggestionRows;
                      final best = find.answer.hasGuess ? find.answer.best : null;
                      final items = listItems;
                      final row = BarSize.row.toDouble();
                      return Container(
                        decoration: BoxDecoration(
                          border: Border(top: BorderSide(color: c.line)),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            if (chipRows > 0)
                              SizedBox(
                                height: row,
                                child: SingleChildScrollView(
                                  scrollDirection: Axis.horizontal,
                                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 7),
                                  child: Row(
                                    children: [
                                      for (final p in find.answer.parts)
                                        Padding(
                                          padding: const EdgeInsets.only(right: 6),
                                          child: PartChip(p, onRemove: () => _words(p.without)),
                                        ),
                                    ],
                                  ),
                                ),
                              ),
                            for (var i = 0; i < ns; i++)
                              SuggestionRow(
                                s: sug.items[i],
                                typed: sug.askedFor,
                                lit: i == sug.highlighted,
                                dense: true,
                                onTap: () {
                                  sug.hover(i);
                                  _enter();
                                },
                                onHover: () => sug.hover(i),
                                onForget: sug.items[i].isHistory ? () => sug.forget(sug.items[i]) : null,
                              ),
                            if (find.askedFor.isNotEmpty && find.results.isEmpty)
                              _NoMatch(
                                find.notice.isNotEmpty ? find.notice : find.askedFor.trim(),
                                isError: find.notice.isNotEmpty,
                              )
                            else if (find.askedFor.isNotEmpty)
                              Expanded(
                                child: ListView.builder(
                                  controller: scroll,
                                  padding: EdgeInsets.zero,
                                  itemExtent: row,
                                  itemCount: items.length,
                                  itemBuilder: (context, at) {
                                    final i = items[at];
                                    if (i < 0) return const _LessSure();
                                    final rowWidget = _Row(
                                      result: find.results[i],
                                      guess: i == 0 && best != null ? best.reason : null,
                                      selected: i == find.selected && sug.highlighted < 0,
                                      onSecondary: (pos) {
                                        find.select(i);
                                        _openMenu(_rowMenu(), pos);
                                      },
                                      onTap: (reveal) {
                                        find.select(i);
                                        _act(reveal: reveal);
                                      },
                                    );
                                    // the first rows of a new answer come in as a short cascade
                                    return at >= BarSize.maxRows
                                        ? rowWidget
                                        : Appear(
                                            key: ValueKey((find.serial, find.results[i].id)),
                                            delay: Appear.stagger(at),
                                            lift: 3,
                                            child: rowWidget,
                                          );
                                  },
                                ),
                              ),
                            if (find.results.isNotEmpty && overflows)
                              _MoreLine(count: find.results.length, more: find.answer.more),
                          ],
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Field extends StatefulWidget {
  const _Field({required this.box, required this.focus, required this.find, required this.onMark});
  final TextEditingController box;
  final FocusNode focus;
  final FindController find;

  /// The n mark: the app menu (open NOBAD Find, Settings, Index, pause, quit).
  final void Function(Offset globalPosition) onMark;

  @override
  State<_Field> createState() => _FieldState();
}

class _FieldState extends State<_Field> {
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
    return Stack(
      children: [
        Positioned.fill(
          bottom: 6, // the key hint has the last few pixels
          child: Padding(
            padding: const EdgeInsets.only(left: 16, right: 20),
            child: Row(
              children: [
                Builder(
                  builder: (ctx) => Pressable(
                    onTap: () {
                      final b = ctx.findRenderObject() as RenderBox?;
                      widget.onMark(b == null ? Offset.zero : b.localToGlobal(Offset(0, b.size.height + 6)));
                    },
                    semanticLabel: 'NOBAD Find menu',
                    tooltip: 'NOBAD Find menu',
                    canRequestFocus: false,
                    ringRadius: NbRadius.controlAll,
                    builder: (context, p) => AnimatedScale(
                      scale: p.lit ? 1.06 : 1,
                      duration: NbMotion.of(context, NbMotion.fast),
                      child: const NbMark(size: 24),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextField(
                    controller: widget.box,
                    focusNode: widget.focus,
                    autofocus: true,
                    cursorColor: c.orange,
                    inputFormatters: [LengthLimitingTextInputFormatter(maxTextLength)],
                    style: NbType.text(16, c.text),
                    decoration: InputDecoration(
                      isCollapsed: true,
                      border: InputBorder.none,
                      hintText: 'Find a file',
                      hintStyle: NbType.text(16, c.dim),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        // the one loud thing: an orange line under the box while it has focus
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          height: 2,
          child: AnimatedScale(
            scale: widget.focus.hasFocus ? 1 : 0,
            alignment: Alignment.centerLeft,
            duration: NbMotion.of(context, const Duration(milliseconds: 250)),
            curve: NbMotion.curve,
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(colors: [c.orange, c.orangeA(0)], stops: const [0, .85]),
              ),
            ),
          ),
        ),
        Positioned(
          right: 20,
          bottom: 3,
          child: IgnorePointer(
            child: ListenableBuilder(
              listenable: widget.find,
              builder: (context, _) => widget.find.results.isEmpty
                  ? const SizedBox.shrink()
                  : widget.find.notice.isNotEmpty
                  ? Text(widget.find.notice, style: NbType.text(NbSize.micro, c.warn))
                  : Text(
                      'Enter opens · Ctrl+Enter shows in folder · Alt+Enter full window · Esc hides',
                      style: NbType.text(NbSize.micro - .5, c.dim),
                    ),
            ),
          ),
        ),
      ],
    );
  }
}

class _Row extends StatefulWidget {
  const _Row({
    required this.result,
    required this.selected,
    required this.onTap,
    required this.onSecondary,
    this.guess,
  });
  final FileResult result;

  /// The best guess's reason when this row is it (a "Best guess" pill in place of the folder's start).
  final String? guess;
  final bool selected;
  final void Function(bool reveal) onTap;
  final void Function(Offset globalPosition) onSecondary;

  @override
  State<_Row> createState() => _RowState();
}

class _RowState extends State<_Row> {
  var _hover = false;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final lit = widget.selected || _hover;
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => widget.onTap(HardwareKeyboard.instance.isControlPressed),
        onSecondaryTapDown: (d) => widget.onSecondary(d.globalPosition),
        child: Semantics(
          selected: widget.selected,
          button: true,
          label: widget.result.name,
          child: SizedBox(
            height: BarSize.row.toDouble(),
            child: Stack(
              children: [
                Positioned.fill(
                  child: AnimatedOpacity(
                    opacity: lit ? (widget.selected ? 1 : .6) : 0,
                    duration: NbMotion.of(context, NbMotion.fast),
                    // the selected row: a soft pill of warm light inside the glass
                    child: Container(
                      margin: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: ShapeDecoration(
                        color: c.orangeA(c.isDark ? .16 : .12),
                        shape: RoundedSuperellipseBorder(borderRadius: BorderRadius.circular(18)),
                      ),
                    ),
                  ),
                ),
                Positioned(
                  left: 0,
                  top: 9,
                  bottom: 9,
                  width: 3,
                  child: AnimatedScale(
                    scale: widget.selected ? 1 : 0,
                    duration: NbMotion.of(context, const Duration(milliseconds: 150)),
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: c.orange,
                        borderRadius: const BorderRadius.horizontal(right: Radius.circular(6)),
                      ),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.only(left: 18, right: 20),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 40,
                        child: Text(
                          kindTag(widget.result.kind),
                          style: NbType.data(9.5, c.orange, weight: FontWeight.w700),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        flex: 6,
                        child: Text(
                          widget.result.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          softWrap: false,
                          style: NbType.text(13.5, c.text, weight: FontWeight.w600),
                        ),
                      ),
                      const SizedBox(width: 12),
                      if (widget.guess != null) ...[
                        Tooltip(
                          message: widget.guess!,
                          child: Container(
                            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
                            decoration: BoxDecoration(color: c.orange, borderRadius: NbRadius.pillAll),
                            child: Text(
                              'Best guess',
                              style: NbType.text(NbSize.micro - 1, c.onOrange, weight: FontWeight.w700, height: 1.3),
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                      ],
                      Expanded(flex: 4, child: TailText(widget.result.dir, style: NbType.data(11, c.dim))),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The bar's "Less sure" line, one row tall (the main window's LessSure, fitted to the bar).
class _LessSure extends StatelessWidget {
  const _LessSure();

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 0),
      child: Row(
        children: [
          Text('Less sure', style: NbType.text(NbSize.micro, c.dim, weight: FontWeight.w600)),
          const SizedBox(width: 12),
          Expanded(child: Container(height: 1, color: c.line)),
        ],
      ),
    );
  }
}

/// More results than fit: how many, and the way to see them all.
class _MoreLine extends StatelessWidget {
  const _MoreLine({required this.count, required this.more});
  final int count;
  final bool more;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      height: BarSize.row.toDouble(),
      padding: const EdgeInsets.symmetric(horizontal: 20),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: c.line)),
      ),
      alignment: Alignment.centerLeft,
      child: Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: '$count${more ? '+' : ''} results',
              style: NbType.text(12, c.text, weight: FontWeight.w600),
            ),
            const TextSpan(text: ' · ↑↓ scroll · Alt+Enter opens them in NOBAD Find'),
          ],
        ),
        style: NbType.text(12, c.dim),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
    );
  }
}

class _NoMatch extends StatelessWidget {
  const _NoMatch(this.words, {this.isError = false});
  final String words;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      height: BarSize.row.toDouble(),
      padding: const EdgeInsets.symmetric(horizontal: 20),
      alignment: Alignment.centerLeft,
      child: isError
          ? Text(words, style: NbType.text(13, c.warn), maxLines: 1, overflow: TextOverflow.ellipsis)
          : Text.rich(
              TextSpan(
                children: [
                  const TextSpan(text: 'No match for '),
                  TextSpan(
                    text: words,
                    style: NbType.text(13, c.text, weight: FontWeight.w600),
                  ),
                ],
              ),
              style: NbType.text(13, c.muted),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
    );
  }
}
