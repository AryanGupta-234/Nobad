/// What can be done with a result, the same everywhere (row and card buttons, the right-click menu, the detail
/// pane or sheet, the quick find bar), each with its keyboard shortcut shown.
library;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

enum ResultAction {
  open('Open', NbGlyph.external, SingleActivator(LogicalKeyboardKey.enter)),
  openWith('Open with…', NbGlyph.external, SingleActivator(LogicalKeyboardKey.enter, control: true, shift: true)),
  reveal('Show in folder', NbGlyph.folder, SingleActivator(LogicalKeyboardKey.enter, control: true)),
  copyPath('Copy path', NbGlyph.copy, SingleActivator(LogicalKeyboardKey.keyC, control: true)),
  copyName('Copy name', NbGlyph.copy, null),
  details('Details', NbGlyph.plus, SingleActivator(LogicalKeyboardKey.space)),
  forget('Forget…', NbGlyph.close, SingleActivator(LogicalKeyboardKey.delete, shift: true));

  const ResultAction(this.label, this.glyph, this.shortcut);
  final String label;
  final NbGlyph glyph;
  final SingleActivator? shortcut;

  /// The buttons a row or card shows when it is selected or hovered; the rest are behind "⋯".
  static const inline = [open, openWith, reveal, copyPath];
  static const more = [copyName, details, forget];
}

/// The menu (right-click, the menu key, "⋯"): every action with its shortcut. [details] false when the detail
/// pane is already on screen.
List<Widget> resultMenuItems(BuildContext context, void Function(ResultAction) onAction, {bool details = true}) {
  final c = NbColors.of(context);
  Widget item(ResultAction a) => MenuItemButton(
    onPressed: () => onAction(a),
    shortcut: a.shortcut,
    leadingIcon: NbIcon(a.glyph, size: 15, color: a == ResultAction.forget ? c.danger : c.muted),
    style: ButtonStyle(
      padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 12)),
      minimumSize: const WidgetStatePropertyAll(Size(220, 34)),
      backgroundColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.hovered) || s.contains(WidgetState.focused) ? c.orangeA(.12) : null,
      ),
      overlayColor: const WidgetStatePropertyAll(Color(0x00000000)),
    ),
    child: Text(a.label, style: NbType.text(13, a == ResultAction.forget ? c.danger : c.text)),
  );
  return [
    for (final a in ResultAction.inline) item(a),
    item(ResultAction.copyName),
    if (details) item(ResultAction.details),
    Container(height: 1, margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 4), color: c.line),
    item(ResultAction.forget),
  ];
}

/// The row of small glass buttons on a selected or hovered result, and "⋯" for the rest.
class InlineActions extends StatelessWidget {
  const InlineActions({super.key, required this.onAction, required this.onMore, this.compact = false});
  final void Function(ResultAction) onAction;

  /// "⋯": opens the menu at this button.
  final void Function(Offset globalPosition) onMore;

  /// Icons only (cards, narrow rows).
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 4,
      runSpacing: 4,
      children: [
        for (final a in ResultAction.inline)
          _ActionChip(
            label: a.label,
            glyph: a.glyph,
            compact: compact,
            onTap: () => onAction(a),
            primary: a == ResultAction.open,
          ),
        Builder(
          builder: (ctx) => _ActionChip(
            label: 'More',
            glyph: null,
            compact: true,
            onTap: () {
              final box = ctx.findRenderObject() as RenderBox?;
              onMore(box == null ? Offset.zero : box.localToGlobal(Offset(0, box.size.height + 4)));
            },
          ),
        ),
      ],
    );
  }
}

class _ActionChip extends StatelessWidget {
  const _ActionChip({
    required this.label,
    required this.glyph,
    required this.onTap,
    this.compact = false,
    this.primary = false,
  });
  final String label;
  final NbGlyph? glyph;
  final VoidCallback onTap;
  final bool compact;
  final bool primary;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      tooltip: compact ? label : null,
      ringRadius: NbRadius.pillAll,
      builder: (context, p) => AnimatedContainer(
        duration: NbMotion.of(context, NbMotion.fast),
        height: 28,
        padding: EdgeInsets.symmetric(horizontal: compact || glyph == null ? 8 : 10),
        decoration: BoxDecoration(
          color: primary ? (p.lit ? c.orange : c.orangeA(.85)) : (p.lit ? c.cardHover : c.card),
          border: Border.all(color: primary ? c.orange : c.line2),
          borderRadius: NbRadius.pillAll,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (glyph != null) NbIcon(glyph!, size: 14, color: primary ? c.onOrange : (p.lit ? c.text : c.muted)),
            if (glyph == null) NbIcon(NbGlyph.more, size: 14, color: p.lit ? c.text : c.muted),
            if (!compact && glyph != null) ...[
              const SizedBox(width: 6),
              Text(
                label,
                style: NbType.text(
                  NbSize.small,
                  primary ? c.onOrange : (p.lit ? c.text : c.muted),
                  weight: FontWeight.w600,
                  height: 1.2,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
