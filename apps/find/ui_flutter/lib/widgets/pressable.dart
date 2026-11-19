/// The base of every clickable thing: hover, keyboard focus (a visible orange ring), press, and Enter/Space to
/// activate. Builds its look from those states, so buttons, tiles, chips and tabs behave the same.
library;

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';

class PressState {
  const PressState({this.hover = false, this.focus = false, this.down = false, this.enabled = true});
  final bool hover;
  final bool focus;
  final bool down;
  final bool enabled;
  bool get lit => enabled && (hover || focus);
}

class Pressable extends StatefulWidget {
  const Pressable({
    super.key,
    required this.builder,
    this.onTap,
    this.semanticLabel,
    this.selected,
    this.focusNode,
    this.autofocus = false,
    this.cursor = SystemMouseCursors.click,
    this.focusRing = true,
    this.ringRadius = NbRadius.controlAll,
    this.canRequestFocus = true,
    this.tooltip,
  });

  final Widget Function(BuildContext context, PressState state) builder;
  final VoidCallback? onTap;
  final String? semanticLabel;
  final bool? selected;
  final FocusNode? focusNode;
  final bool autofocus;
  final MouseCursor cursor;
  final bool focusRing;
  final BorderRadius ringRadius;
  final bool canRequestFocus;
  final String? tooltip;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  var _hover = false, _focus = false, _down = false;

  bool get _enabled => widget.onTap != null;

  late final _actions = <Type, Action<Intent>>{
    ActivateIntent: CallbackAction<ActivateIntent>(onInvoke: (_) {
      widget.onTap?.call();
      return null;
    }),
  };

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final state = PressState(hover: _hover, focus: _focus, down: _down, enabled: _enabled);
    Widget child = widget.builder(context, state);
    if (widget.focusRing) {
      child = DecoratedBox(
        position: DecorationPosition.foreground,
        decoration: BoxDecoration(
          borderRadius: widget.ringRadius,
          border: Border.all(color: _focus && _enabled ? c.orange : const Color(0x00000000), width: 2,
              strokeAlign: BorderSide.strokeAlignOutside),
        ),
        child: child,
      );
    }
    return Semantics(
      button: true,
      enabled: _enabled,
      selected: widget.selected,
      label: widget.semanticLabel,
      tooltip: widget.tooltip,
      child: FocusableActionDetector(
        enabled: _enabled && widget.canRequestFocus,
        focusNode: widget.focusNode,
        autofocus: widget.autofocus,
        mouseCursor: _enabled ? widget.cursor : SystemMouseCursors.basic,
        actions: _actions,
        shortcuts: const {
          SingleActivator(LogicalKeyboardKey.enter): ActivateIntent(),
          SingleActivator(LogicalKeyboardKey.space): ActivateIntent(),
        },
        onShowHoverHighlight: (v) => setState(() => _hover = v),
        onShowFocusHighlight: (v) => setState(() => _focus = v),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapDown: _enabled ? (_) => setState(() => _down = true) : null,
          onTapCancel: () => setState(() => _down = false),
          onTapUp: (_) => setState(() => _down = false),
          onTap: widget.onTap,
          child: child,
        ),
      ),
    );
  }
}
