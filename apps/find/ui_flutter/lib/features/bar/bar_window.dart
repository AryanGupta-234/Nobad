/// The quick find bar (`--bar`): frameless, on top, 640 px wide, a third of the way down the monitor with the
/// mouse; up to 8 results; Enter opens, Ctrl+Enter shows in folder, Alt+Enter hands the words to the main window,
/// Esc hides. The engine's bar hotkey shows it.
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
  late final FindController find = FindController(
    widget.engine,
    limit: BarSize.maxRows,
    debounce: const Duration(milliseconds: 90),
  );
  final box = TextEditingController();
  final focus = FocusNode(debugLabel: 'bar box');
  late final StreamSubscription<EngineEvent> _shows;
  int _rows = -1;

  @override
  void initState() {
    super.initState();
    box.addListener(() => find.setText(box.text));
    find.addListener(_fit);
    _shows = widget.engine.events.listen((e) {
      if (e is ShowEvent && e.what == 'bar') show();
      if (e is QuittingEvent) widget.window.close();
    });
    widget.demo?.run(widget.engine, box, find, 'bar', after: hide);
    _life; // start listening
  }

  /// Rows the window needs: the results, or one for "No match for …" or a failed open.
  int get rowsNeeded {
    if (find.text.trim().isEmpty || find.askedFor.isEmpty) return 0;
    return find.results.isEmpty ? 1 : find.results.length;
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

  void show() {
    _hiding?.cancel();
    _visible = true;
    _settling = true;
    _settle?.cancel();
    _settle = Timer(const Duration(milliseconds: 400), () => _settling = false);
    box.clear();
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
    box.clear();
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
    _life.dispose();
    _settle?.cancel();
    find.dispose();
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
      radius: 12,
      fill: c.glass ? c.panel : c.surface,
      child: CallbackShortcuts(
        bindings: {
          const SingleActivator(LogicalKeyboardKey.arrowDown): () => find.move(1),
          const SingleActivator(LogicalKeyboardKey.arrowUp): () => find.move(-1),
          const SingleActivator(LogicalKeyboardKey.enter): _act,
          const SingleActivator(LogicalKeyboardKey.numpadEnter): _act,
          const SingleActivator(LogicalKeyboardKey.enter, control: true): () => _act(reveal: true),
          const SingleActivator(LogicalKeyboardKey.enter, alt: true): _toMain,
          const SingleActivator(LogicalKeyboardKey.escape): hide,
        },
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              height: BarSize.field - 2,
              child: _Field(box: box, focus: focus, find: find),
            ),
            Expanded(
              child: ListenableBuilder(
                listenable: find,
                builder: (context, _) {
                  if (rowsNeeded == 0) return const SizedBox.shrink();
                  return Container(
                    decoration: BoxDecoration(
                      border: Border(top: BorderSide(color: c.line)),
                    ),
                    child: find.results.isEmpty
                        ? _NoMatch(
                            find.notice.isNotEmpty ? find.notice : find.askedFor.trim(),
                            isError: find.notice.isNotEmpty,
                          )
                        : Column(
                            children: [
                              for (var i = 0; i < find.results.length; i++)
                                Appear(
                                  key: ValueKey((find.serial, find.results[i].id)),
                                  delay: Appear.stagger(i),
                                  lift: 3,
                                  child: _Row(
                                    result: find.results[i],
                                    selected: i == find.selected,
                                    onTap: (reveal) {
                                      find.select(i);
                                      _act(reveal: reveal);
                                    },
                                  ),
                                ),
                            ],
                          ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Field extends StatefulWidget {
  const _Field({required this.box, required this.focus, required this.find});
  final TextEditingController box;
  final FocusNode focus;
  final FindController find;

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
        Padding(
          padding: const EdgeInsets.only(left: 16, right: 20),
          child: Row(
            children: [
              const NbMark(size: 30),
              const SizedBox(width: 14),
              Expanded(
                child: TextField(
                  controller: widget.box,
                  focusNode: widget.focus,
                  autofocus: true,
                  cursorColor: c.orange,
                  inputFormatters: [LengthLimitingTextInputFormatter(maxTextLength)],
                  style: NbType.display(24, c.text, weight: 330),
                  decoration: InputDecoration(
                    isCollapsed: true,
                    border: InputBorder.none,
                    hintText: 'Find a file',
                    hintStyle: NbType.display(24, c.dim, weight: 300),
                  ),
                ),
              ),
            ],
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
          bottom: 4,
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
  const _Row({required this.result, required this.selected, required this.onTap});
  final FileResult result;
  final bool selected;
  final void Function(bool reveal) onTap;

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
                        shape: RoundedSuperellipseBorder(borderRadius: BorderRadius.circular(14)),
                      ),
                    ),
                  ),
                ),
                Positioned(
                  left: 0,
                  top: 8,
                  bottom: 8,
                  width: 3,
                  child: AnimatedScale(
                    scale: widget.selected ? 1 : 0,
                    duration: NbMotion.of(context, const Duration(milliseconds: 150)),
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: c.orange,
                        borderRadius: const BorderRadius.horizontal(right: Radius.circular(3)),
                      ),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.only(left: 18, right: 20),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 46,
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
                          style: NbType.text(14.5, c.text, weight: FontWeight.w600),
                        ),
                      ),
                      const SizedBox(width: 12),
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
