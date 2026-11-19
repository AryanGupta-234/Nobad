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

class BarWindow extends StatefulWidget {
  const BarWindow({super.key, required this.engine, this.window = const NoWindow(), this.demo});
  final EngineApi engine;
  final Demo? demo;
  final WindowControl window;

  @override
  State<BarWindow> createState() => _BarWindowState();
}

class _BarWindowState extends State<BarWindow> {
  late final FindController find =
      FindController(widget.engine, limit: BarSize.maxRows, debounce: const Duration(milliseconds: 90));
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

  void show() {
    box.clear();

    _rows = -1;
    widget.window.showBar();
    _fit();
    focus.requestFocus();
    unawaited(widget.engine.uiShown('bar').catchError((Object _) {}));
  }

  void hide() {
    widget.window.hide();
    box.clear();
    unawaited(widget.engine.uiHidden('bar').catchError((Object _) {}));
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
    find.dispose();
    box.dispose();
    focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      decoration: BoxDecoration(
        color: c.glass ? c.bg.withValues(alpha: c.isDark ? .55 : .7) : c.bg,
        border: Border.all(color: c.line2),
        borderRadius: BorderRadius.circular(10),
      ),
      clipBehavior: Clip.antiAlias,
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
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SizedBox(height: BarSize.field - 2, child: _Field(box: box, focus: focus, find: find)),
          Expanded(
            child: ListenableBuilder(
              listenable: find,
              builder: (context, _) {
                if (rowsNeeded == 0) return const SizedBox.shrink();
                return Container(
                  decoration: BoxDecoration(border: Border(top: BorderSide(color: c.line))),
                  child: find.results.isEmpty
                      ? _NoMatch(find.notice.isNotEmpty ? find.notice : find.askedFor.trim(),
                          isError: find.notice.isNotEmpty)
                      : Column(children: [
                          for (var i = 0; i < find.results.length; i++)
                            _Row(
                              result: find.results[i],
                              selected: i == find.selected,
                              onTap: (reveal) {
                                find.select(i);
                                _act(reveal: reveal);
                              },
                            ),
                        ]),
                );
              },
            ),
          ),
        ]),
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
    return Stack(children: [
      Padding(
        padding: const EdgeInsets.only(left: 16, right: 20),
        child: Row(children: [
          const NbMark(size: 30),
          const SizedBox(width: 14),
          Expanded(
            child: TextField(
              controller: widget.box,
              focusNode: widget.focus,
              autofocus: true,
              cursorColor: c.orange,
              style: NbType.text(NbSize.field, c.text),
              decoration: InputDecoration(
                isCollapsed: true,
                border: InputBorder.none,
                hintText: 'Find a file',
                hintStyle: NbType.text(NbSize.field, c.dim),
              ),
            ),
          ),
        ]),
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
            decoration: BoxDecoration(gradient: LinearGradient(colors: [c.orange, c.orangeA(0)], stops: const [0, .85])),
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
                    : Text('Enter opens · Ctrl+Enter shows in folder · Alt+Enter full window · Esc hides',
                        style: NbType.text(NbSize.micro - .5, c.dim)),
          ),
        ),
      ),
    ]);
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
            child: Stack(children: [
              Positioned.fill(
                child: AnimatedOpacity(
                  opacity: lit ? (widget.selected ? 1 : .6) : 0,
                  duration: NbMotion.of(context, NbMotion.fast),
                  child: DecoratedBox(
                      decoration: BoxDecoration(
                          gradient: LinearGradient(colors: [c.orangeA(.16), c.orangeA(0)], stops: const [0, .75]))),
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
                      decoration: BoxDecoration(color: c.orange,
                          borderRadius: const BorderRadius.horizontal(right: Radius.circular(3)))),
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(left: 18, right: 20),
                child: Row(children: [
                  SizedBox(
                      width: 46,
                      child: Text(kindTag(widget.result.kind),
                          style: NbType.data(9.5, c.orange, weight: FontWeight.w700))),
                  const SizedBox(width: 12),
                  Expanded(
                    flex: 6,
                    child: Text(widget.result.name, maxLines: 1, overflow: TextOverflow.ellipsis, softWrap: false,
                        style: NbType.text(14.5, c.text, weight: FontWeight.w600)),
                  ),
                  const SizedBox(width: 12),
                  Expanded(flex: 4, child: TailText(widget.result.dir, style: NbType.data(11, c.dim))),
                ]),
              ),
            ]),
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
              TextSpan(children: [
                const TextSpan(text: 'No match for '),
                TextSpan(text: words, style: NbType.text(13, c.text, weight: FontWeight.w600)),
              ]),
              style: NbType.text(13, c.muted),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
    );
  }
}
