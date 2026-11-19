/// Controls: buttons, the switch, drop-down choices, text and number fields, filter chips, key caps.
library;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import 'icons.dart';
import 'pressable.dart';

enum NbButtonKind { primary, ghost, danger, quiet }

/// A button that says exactly what happens ("Download", "Pause for 1 hour"). Sentence case.
class NbButton extends StatelessWidget {
  const NbButton(
    this.label, {
    super.key,
    this.onPressed,
    this.kind = NbButtonKind.primary,
    this.icon,
    this.small = false,
    this.autofocus = false,
  });
  final String label;
  final VoidCallback? onPressed;
  final NbButtonKind kind;
  final NbGlyph? icon;
  final bool small;
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Pressable(
      onTap: onPressed,
      autofocus: autofocus,
      semanticLabel: label,
      builder: (context, s) {
        final enabled = s.enabled;
        final (Color bg, Color fg, Color edge) = switch (kind) {
          NbButtonKind.primary => (s.down ? Color.lerp(c.orange, c.shadow, .12)! : c.orange, c.onOrange, c.orange),
          NbButtonKind.ghost => (
            s.lit ? c.orangeA(.06) : const Color(0x00000000),
            c.text,
            s.lit ? c.orangeA(.8) : c.line2,
          ),
          NbButtonKind.danger => (
            s.lit ? c.danger.withValues(alpha: .08) : const Color(0x00000000),
            c.danger,
            c.danger.withValues(alpha: s.lit ? .9 : .5),
          ),
          NbButtonKind.quiet => (
            s.lit ? c.orangeA(.08) : const Color(0x00000000),
            s.lit ? c.orange : c.muted,
            const Color(0x00000000),
          ),
        };
        return AnimatedOpacity(
          opacity: enabled ? 1 : .45,
          duration: NbMotion.of(context, NbMotion.fast),
          child: AnimatedContainer(
            duration: NbMotion.of(context, NbMotion.fast),
            curve: NbMotion.curve,
            height: small ? 28 : 32,
            padding: EdgeInsets.symmetric(horizontal: small ? 10 : 14),
            decoration: BoxDecoration(
              color: bg,
              border: Border.all(color: edge),
              borderRadius: NbRadius.controlAll,
              boxShadow: [
                if (kind == NbButtonKind.primary && s.lit && enabled)
                  BoxShadow(color: c.orangeA(.3), blurRadius: 10, offset: const Offset(0, 3), spreadRadius: -5),
              ],
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (icon != null) ...[NbIcon(icon!, size: small ? 14 : 16, color: fg), const SizedBox(width: 7)],
                Text(label, style: NbType.text(small ? NbSize.small : 13, fg, weight: FontWeight.w600, height: 1.2)),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// On/off. The thumb slides; on is the orange track (app.css .switch).
class NbSwitch extends StatelessWidget {
  const NbSwitch({super.key, required this.value, required this.onChanged, required this.label});
  final bool value;
  final ValueChanged<bool>? onChanged;
  final String label;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final d = NbMotion.of(context, NbMotion.base);
    return Semantics(
      toggled: value,
      child: Pressable(
        onTap: onChanged == null ? null : () => onChanged!(!value),
        semanticLabel: label,
        ringRadius: NbRadius.pillAll,
        builder: (context, s) => AnimatedContainer(
          duration: d,
          curve: NbMotion.curve,
          width: 40,
          height: 20,
          decoration: BoxDecoration(
            color: value ? c.orangeA(c.isDark ? .22 : .14) : c.raised,
            border: Border.all(color: value ? c.orange : (s.lit ? c.orangeA(.6) : c.line2)),
            borderRadius: NbRadius.pillAll,
          ),
          child: AnimatedAlign(
            duration: d,
            curve: NbMotion.curve,
            alignment: value ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
              width: 12,
              height: 12,
              margin: const EdgeInsets.symmetric(horizontal: 4),
              decoration: BoxDecoration(shape: BoxShape.circle, color: value ? c.orange : c.dim),
            ),
          ),
        ),
      ),
    );
  }
}

/// A drop-down choice: [options] are (value, label). [highlight] marks a choice that filters (orange edge).
class NbSelect extends StatefulWidget {
  const NbSelect({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
    this.highlight = false,
    this.compact = false,
    this.label,
    this.maxWidth = 260,
  });
  final String value;
  final List<(String, String)> options;
  final ValueChanged<String> onChanged;
  final bool highlight;
  final bool compact;
  final String? label;
  final double maxWidth;

  @override
  State<NbSelect> createState() => _NbSelectState();
}

class _NbSelectState extends State<NbSelect> {
  final _menu = MenuController();

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final current = widget.options.firstWhere((o) => o.$1 == widget.value, orElse: () => widget.options.first);
    return MenuAnchor(
      controller: _menu,
      alignmentOffset: const Offset(0, 4),
      menuChildren: [
        for (final o in widget.options)
          MenuItemButton(
            onPressed: () => widget.onChanged(o.$1),
            style: ButtonStyle(
              padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 12)),
              minimumSize: const WidgetStatePropertyAll(Size(180, 34)),
              backgroundColor: WidgetStateProperty.resolveWith(
                (s) => s.contains(WidgetState.hovered) || s.contains(WidgetState.focused) ? c.orangeA(.1) : null,
              ),
              overlayColor: const WidgetStatePropertyAll(Color(0x00000000)),
            ),
            leadingIcon: SizedBox(
              width: 16,
              child: o.$1 == widget.value ? NbIcon(NbGlyph.check, size: 15, color: c.orange) : null,
            ),
            child: Text(
              o.$2,
              style: NbType.text(
                13,
                o.$1 == widget.value ? c.orange : c.text,
                weight: o.$1 == widget.value ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
      ],
      builder: (context, menu, _) => Pressable(
        onTap: () => menu.isOpen ? menu.close() : menu.open(),
        semanticLabel: widget.label == null ? current.$2 : '${widget.label}: ${current.$2}',
        builder: (context, s) {
          final on = widget.highlight;
          return AnimatedContainer(
            duration: NbMotion.of(context, NbMotion.fast),
            constraints: BoxConstraints(maxWidth: widget.maxWidth),
            height: widget.compact ? 28 : 30,
            padding: const EdgeInsets.only(left: 11, right: 7),
            decoration: BoxDecoration(
              color: on ? c.orangeA(.08) : (widget.compact ? c.panel : c.raised),
              border: Border.all(color: on ? c.orangeA(.75) : (s.lit ? c.orangeA(.6) : c.line2)),
              borderRadius: NbRadius.controlAll,
            ),
            child: AnimatedSize(
              duration: NbMotion.of(context, NbMotion.base),
              curve: NbMotion.curve,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Flexible(
                    child: Text(
                      current.$2,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: NbType.text(
                        widget.compact ? NbSize.small : 13,
                        on ? c.orange : (s.lit ? c.text : c.muted),
                        weight: on ? FontWeight.w600 : FontWeight.w400,
                        height: 1.2,
                      ),
                    ),
                  ),
                  const SizedBox(width: 4),
                  NbIcon(NbGlyph.chevron, size: 16, color: on ? c.orange : c.dim),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

/// A filter that's a button rather than a list (Any folder, Here, Clear filters).
class NbChipButton extends StatelessWidget {
  const NbChipButton(
    this.label, {
    super.key,
    required this.onTap,
    this.on = false,
    this.dashed = false,
    this.icon,
    this.tooltip,
  });
  final String label;
  final VoidCallback onTap;
  final bool on;
  final bool dashed;
  final NbGlyph? icon;
  final String? tooltip;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget w = Pressable(
      onTap: onTap,
      semanticLabel: label,
      builder: (context, s) => AnimatedContainer(
        duration: NbMotion.of(context, NbMotion.fast),
        constraints: const BoxConstraints(maxWidth: 260),
        height: 28,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(
          color: on ? c.orangeA(.08) : c.panel,
          border: dashed ? null : Border.all(color: on ? c.orangeA(.75) : (s.lit ? c.orangeA(.6) : c.line2)),
          borderRadius: NbRadius.controlAll,
        ),
        foregroundDecoration: dashed
            ? _DashedBorder(color: s.lit ? c.orangeA(.7) : c.line2, radius: NbRadius.control)
            : null,
        child: AnimatedSize(
          duration: NbMotion.of(context, NbMotion.base),
          curve: NbMotion.curve,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null) ...[NbIcon(icon!, size: 14, color: on ? c.orange : c.dim), const SizedBox(width: 6)],
              Flexible(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: NbType.text(
                    NbSize.small,
                    on ? c.orange : (s.lit ? c.text : c.muted),
                    weight: on ? FontWeight.w600 : FontWeight.w400,
                    height: 1.2,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (tooltip != null) w = Tooltip(message: tooltip, child: w);
    return w;
  }
}

class _DashedBorder extends Decoration {
  const _DashedBorder({required this.color, required this.radius});
  final Color color;
  final Radius radius;
  @override
  BoxPainter createBoxPainter([VoidCallback? onChanged]) => _DashedPainter(color, radius);
}

class _DashedPainter extends BoxPainter {
  _DashedPainter(this.color, this.radius);
  final Color color;
  final Radius radius;
  @override
  void paint(Canvas canvas, Offset offset, ImageConfiguration cfg) {
    final r = RRect.fromRectAndRadius((offset & cfg.size!).deflate(.5), radius);
    final path = Path()..addRRect(r);
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke;
    for (final m in path.computeMetrics()) {
      for (var d = 0.0; d < m.length; d += 7) {
        canvas.drawPath(m.extractPath(d, d + 4), p);
      }
    }
  }
}

/// A text or whole-number field for the Settings rows. Saves on Enter and when it loses focus.
class NbField extends StatefulWidget {
  const NbField({
    super.key,
    required this.value,
    required this.onSubmit,
    this.number = false,
    this.width = 190,
    required this.label,
  });
  final String value;
  final ValueChanged<String> onSubmit;
  final bool number;
  final double width;
  final String label;

  @override
  State<NbField> createState() => _NbFieldState();
}

class _NbFieldState extends State<NbField> {
  late final _ctl = TextEditingController(text: widget.value);
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    _focus.addListener(() {
      if (!_focus.hasFocus) _submit();
      setState(() {});
    });
  }

  @override
  void didUpdateWidget(NbField old) {
    super.didUpdateWidget(old);
    if (old.value != widget.value && !_focus.hasFocus) _ctl.text = widget.value;
  }

  void _submit() {
    if (_ctl.text != widget.value) widget.onSubmit(_ctl.text);
  }

  @override
  void dispose() {
    _ctl.dispose();
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    OutlineInputBorder edge(Color col) => OutlineInputBorder(
      borderRadius: NbRadius.controlAll,
      borderSide: BorderSide(color: col),
    );
    return SizedBox(
      width: widget.number ? 96 : widget.width,
      child: Semantics(
        label: widget.label,
        textField: true,
        child: TextField(
          controller: _ctl,
          focusNode: _focus,
          onSubmitted: (_) => _submit(),
          keyboardType: widget.number ? TextInputType.number : TextInputType.text,
          inputFormatters: widget.number ? [FilteringTextInputFormatter.digitsOnly] : null,
          style: NbType.data(13, c.text),
          cursorColor: c.orange,
          decoration: InputDecoration(
            isDense: true,
            filled: true,
            fillColor: c.raised,
            contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
            enabledBorder: edge(c.line2),
            focusedBorder: edge(c.orange),
          ),
        ),
      ),
    );
  }
}

/// A key cap: Enter, Ctrl, ↑.
class Kbd extends StatelessWidget {
  const Kbd(this.label, {super.key});
  final String label;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        color: c.panel,
        borderRadius: NbRadius.keyAll,
        border: Border(
          top: BorderSide(color: c.line2),
          left: BorderSide(color: c.line2),
          right: BorderSide(color: c.line2),
          bottom: BorderSide(color: c.line2, width: 2),
        ),
      ),
      child: Text(label, style: NbType.data(NbSize.micro, c.text, height: 1.5)),
    );
  }
}

/// A row of key hints: [(keys, what)] → "↑ ↓ move   Enter open".
class KeyHints extends StatelessWidget {
  const KeyHints(this.hints, {super.key});
  final List<(List<String>, String)> hints;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Wrap(
      spacing: 14,
      runSpacing: 6,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        for (final (keys, what) in hints)
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final k in keys) ...[Kbd(k), const SizedBox(width: 3)],
              const SizedBox(width: 3),
              Text(what, style: NbType.text(NbSize.small, c.dim, height: 1.2)),
            ],
          ),
      ],
    );
  }
}

/// A row of choices, one lit (a small glass pill): Settings' "English first / Many languages / Hindi + English",
/// "Whole PC / My files / Custom". [badge] marks one choice ("Recommended").
class NbSegmented<T> extends StatelessWidget {
  const NbSegmented({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
    this.badge,
    this.badgeText = 'Recommended',
  });
  final T? value;
  final List<(T, String)> options;
  final ValueChanged<T>? onChanged;
  final T? badge;
  final String badgeText;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget seg(T v, String label) {
      final on = v == value;
      return Pressable(
        onTap: onChanged == null ? null : () => onChanged!(v),
        selected: on,
        semanticLabel: v == badge ? '$label, $badgeText' : label,
        ringRadius: NbRadius.pillAll,
        builder: (context, p) => AnimatedContainer(
          duration: NbMotion.of(context, NbMotion.base),
          curve: NbMotion.curve,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
          decoration: BoxDecoration(
            color: on ? c.orangeA(c.isDark ? .16 : .12) : (p.lit ? c.cardHover : null),
            border: Border.all(color: on ? c.orangeA(.55) : const Color(0x00000000)),
            borderRadius: NbRadius.pillAll,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label,
                style: NbType.text(
                  13,
                  on ? c.text : (p.lit ? c.muted : c.dim),
                  weight: on ? FontWeight.w600 : FontWeight.w500,
                  height: 1.2,
                ),
              ),
              if (v == badge) ...[
                const SizedBox(width: 7),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                  decoration: BoxDecoration(color: c.orangeA(.14), borderRadius: NbRadius.pillAll),
                  child: Text(badgeText, style: NbType.text(10.5, c.orange, weight: FontWeight.w600, height: 1.3)),
                ),
              ],
            ],
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: c.card,
        border: Border.all(color: c.line),
        borderRadius: NbRadius.pillAll,
      ),
      child: Wrap(spacing: 2, runSpacing: 2, children: [for (final (v, l) in options) seg(v, l)]),
    );
  }
}
