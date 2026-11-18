/// The quick find bar (`--bar`): frameless, on top, 640 px wide, a third of the way down the monitor with the
/// mouse; up to 8 results; Enter opens, Ctrl+Enter shows in folder, Esc hides. The engine's bar hotkey shows it.
library;

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/typography.dart';
import '../../engine/events.dart';
import '../../engine/models/result.dart';
import '../../engine/rpc.dart';
import '../../platform/window.dart';
import '../../state/search_controller.dart';
import '../../widgets/common.dart';

class BarWindow extends StatefulWidget {
  const BarWindow({super.key, required this.engine, this.window = const NoWindow()});
  final Engine engine;
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
    });
  }

  /// Rows the window needs: the results, or one for "No match for …".
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
  }

  void hide() {
    widget.window.hide();
    box.clear();
  }

  Future<void> _act({bool reveal = false}) async {
    final ok = reveal ? await find.revealSelected() : await find.openSelected();
    if (ok) hide();
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
    return Container(
      decoration: BoxDecoration(
        color: Nb.bg,
        border: Border.all(color: Nb.line2),
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
                  decoration: const BoxDecoration(border: Border(top: BorderSide(color: Nb.line))),
                  child: find.results.isEmpty
                      ? _NoMatch(find.askedFor.trim())
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
              cursorColor: Nb.orange,
              style: NbType.text(21),
              decoration: InputDecoration(
                isCollapsed: true,
                border: InputBorder.none,
                hintText: 'Find a file',
                hintStyle: NbType.text(21, color: Nb.dim),
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
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOutCubic,
          child: DecoratedBox(
            decoration: BoxDecoration(
                gradient: LinearGradient(colors: [Nb.orange, Nb.orangeA(0)], stops: const [0, .85])),
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
                : Text('Enter opens · Ctrl+Enter shows in folder · Esc hides', style: NbType.label(10)),
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
    final lit = widget.selected || _hover;
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => widget.onTap(HardwareKeyboard.instance.isControlPressed),
        child: SizedBox(
          height: BarSize.row.toDouble(),
          child: Stack(children: [
            Positioned.fill(
              child: AnimatedOpacity(
                opacity: lit ? 1 : 0,
                duration: const Duration(milliseconds: 120),
                child: DecoratedBox(
                    decoration: BoxDecoration(
                        gradient: LinearGradient(colors: [Nb.orangeA(.16), Nb.orangeA(0)], stops: const [0, .75]))),
              ),
            ),
            Positioned(
              left: 0,
              top: 8,
              bottom: 8,
              width: 3,
              child: AnimatedScale(
                scale: widget.selected ? 1 : 0,
                duration: const Duration(milliseconds: 150),
                child: const DecoratedBox(
                    decoration: BoxDecoration(color: Nb.orange,
                        borderRadius: BorderRadius.horizontal(right: Radius.circular(3)))),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(left: 18, right: 20),
              child: Row(children: [
                SizedBox(
                    width: 46,
                    child: Text(kindTag(widget.result.kind),
                        style: NbType.label(9.5, weight: FontWeight.w700, color: Nb.orange, spacing: .6))),
                const SizedBox(width: 12),
                Expanded(
                  flex: 6,
                  child: Text(widget.result.name, maxLines: 1, overflow: TextOverflow.ellipsis, softWrap: false,
                      style: NbType.text(14.5, weight: FontWeight.w600)),
                ),
                const SizedBox(width: 12),
                Expanded(flex: 4, child: TailText(widget.result.dir, style: NbType.label(11))),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _NoMatch extends StatelessWidget {
  const _NoMatch(this.words);
  final String words;

  @override
  Widget build(BuildContext context) => Container(
        height: BarSize.row.toDouble(),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        alignment: Alignment.centerLeft,
        child: Text.rich(
          TextSpan(children: [
            const TextSpan(text: 'No match for '),
            TextSpan(text: words, style: NbType.text(13, weight: FontWeight.w600)),
          ]),
          style: NbType.text(13, color: Nb.muted),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
      );
}
