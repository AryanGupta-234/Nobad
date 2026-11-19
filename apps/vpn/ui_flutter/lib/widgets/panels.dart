/// Surfaces and read-outs: the mark, panels, the page's display line, metrics, notices and toasts.
library;

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import '../state/vpn_controller.dart';
import 'controls.dart';
import 'glass.dart';
import 'icons.dart';
import 'pressable.dart';

class NbMark extends StatelessWidget {
  const NbMark({super.key, this.size = 34});
  final double size;

  @override
  Widget build(BuildContext context) {
    final px = (size * MediaQuery.devicePixelRatioOf(context)).round();
    return Image.asset('assets/nobad-mark.png', width: size, height: size, cacheWidth: px, cacheHeight: px,
        semanticLabel: 'NOBAD', filterQuality: FilterQuality.medium);
  }
}

/// A grouped surface of frosted glass (fill and rim, no blur). [edge] tints the rim (a state's colour).
class NbPanel extends StatelessWidget {
  const NbPanel({super.key, required this.child, this.padding = const EdgeInsets.all(NbSpace.x4), this.edge, this.radius = 10});
  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? edge;
  final double radius;

  @override
  Widget build(BuildContext context) => Glass(radius: radius, padding: padding, rim: edge, child: child);
}

/// The one display line of a screen ("SERVERS", "SETTINGS"): Arial Black, upper case, with the orange signal rule.
class PageTitle extends StatelessWidget {
  const PageTitle(this.text, {super.key, this.size = NbSize.page, this.sub});
  final String text;
  final double size;
  final String? sub;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Semantics(
      header: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(text.toUpperCase(), style: NbType.display(size, c.text)),
          const SizedBox(height: 8),
          const SignalRule(width: 32),
          if (sub != null) ...[
            const SizedBox(height: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 620),
              child: Text(sub!, style: NbType.text(NbSize.body, c.muted, height: 1.45)),
            ),
          ],
        ],
      ),
    );
  }
}

/// The short orange line with its glow: the NOBAD signal under a display line.
class SignalRule extends StatelessWidget {
  const SignalRule({super.key, this.width = 46, this.color});
  final double width;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? NbColors.of(context).orange;
    return Container(
      width: width,
      height: 2,
      decoration: BoxDecoration(
        color: c,
        borderRadius: NbRadius.pillAll,
        boxShadow: [BoxShadow(color: c.withValues(alpha: .55), blurRadius: 12)],
      ),
    );
  }
}

/// A measured value: its name in reading text, the value in Cascadia Mono.
class Metric extends StatelessWidget {
  const Metric(this.label, this.value, {super.key, this.color, this.big = false});
  final String label;
  final String value;
  final Color? color;
  final bool big;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, style: NbType.text(NbSize.caption, c.muted, height: 1.3)),
        const SizedBox(height: 2),
        Text(value, style: NbType.data(big ? NbSize.field : NbSize.body, color ?? c.text, height: 1.2),
            maxLines: 1, overflow: TextOverflow.ellipsis),
      ],
    );
  }
}

enum NoticeKind { info, warn, bad }

class NoticeAction {
  const NoticeAction(this.label, this.onTap, {this.primary = false});
  final String label;
  final VoidCallback onTap;
  final bool primary;
}

/// A notice about the protection or the setup: a coloured edge, the title, a plain sentence, its actions.
class Notice extends StatelessWidget {
  const Notice({super.key, required this.kind, required this.title, this.detail = '', this.actions = const [], this.onClose});
  final NoticeKind kind;
  final String title;
  final String detail;
  final List<NoticeAction> actions;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final edge = switch (kind) {
      NoticeKind.info => c.orange,
      NoticeKind.warn => c.amber,
      NoticeKind.bad => c.blocked,
    };
    return Semantics(
      liveRegion: kind != NoticeKind.info,
      container: true,
      child: Container(
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          color: c.isDark ? const Color(0xE6151820) : const Color(0xF2FFFFFF),
          borderRadius: NbRadius.rowAll,
          border: Border.all(color: edge.withValues(alpha: .45)),
          boxShadow: [BoxShadow(color: c.float, blurRadius: 30, offset: const Offset(0, 10), spreadRadius: -16)],
        ),
        child: Stack(
          children: [
            Positioned(left: 0, top: 0, bottom: 0, width: 3, child: ColoredBox(color: edge)),
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(title, style: NbType.text(NbSize.body, c.text, weight: FontWeight.w600, height: 1.35)),
                        if (detail.isNotEmpty) ...[
                          const SizedBox(height: 3),
                          Text(detail, style: NbType.text(NbSize.small, c.muted, height: 1.45)),
                        ],
                        if (actions.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Wrap(
                            spacing: NbSpace.x2,
                            runSpacing: NbSpace.x2,
                            children: [
                              for (final a in actions)
                                NbButton(a.label, small: true, onPressed: a.onTap,
                                    kind: a.primary ? NbButtonKind.primary : NbButtonKind.ghost),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                  if (onClose != null)
                    Pressable(
                      onTap: onClose,
                      semanticLabel: 'Close',
                      tooltip: 'Close',
                      builder: (context, s) => Padding(
                        padding: const EdgeInsets.all(6),
                        child: NbIcon(NbGlyph.close, size: 16, color: s.lit ? c.text : c.dim),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Toasts: the newest few, bottom right, each closing by itself.
class ToastStack extends StatelessWidget {
  const ToastStack({super.key, required this.vpn});
  final VpnController vpn;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: vpn,
      builder: (context, _) => Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final t in vpn.toasts)
            Padding(
              key: ValueKey(t.id),
              padding: const EdgeInsets.only(top: NbSpace.x2),
              child: TweenAnimationBuilder<double>(
                tween: Tween(begin: 0, end: 1),
                duration: NbMotion.of(context, NbMotion.slow),
                curve: NbMotion.curve,
                builder: (context, v, child) => Opacity(
                  opacity: v,
                  child: Transform.translate(offset: Offset(24 * (1 - v), 0), child: child),
                ),
                child: Semantics(
                liveRegion: true,
                child: Pressable(
                  onTap: () => vpn.dismissToast(t.id),
                  semanticLabel: t.text,
                  focusRing: false,
                  builder: (context, s) => Container(
                    constraints: const BoxConstraints(maxWidth: 400),
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                      color: c.surface,
                      border: Border.all(color: (t.good ? c.sealed : c.orange).withValues(alpha: .55)),
                      borderRadius: NbRadius.rowAll,
                      boxShadow: [BoxShadow(color: c.shadow.withValues(alpha: .45), blurRadius: 36,
                          offset: const Offset(0, 14), spreadRadius: -14)],
                    ),
                    child: Text(t.text, style: NbType.text(NbSize.body, c.text, height: 1.4)),
                  ),
                ),
              ),
              ),
            ),
        ],
      ),
    );
  }
}

/// A number that eases to its new value (a counter): latency, loss, rates. [format] turns the value into text;
/// null is shown as a dash at once. With animations off it just changes.
class EasedNumber extends StatelessWidget {
  const EasedNumber(this.value, {super.key, required this.format, required this.style});
  final double? value;
  final String Function(double) format;
  final TextStyle style;

  @override
  Widget build(BuildContext context) {
    if (value == null) return Text('—', style: style, maxLines: 1);
    return TweenAnimationBuilder<double>(
      tween: Tween(end: value),
      duration: NbMotion.of(context, NbMotion.slow),
      curve: NbMotion.curve,
      builder: (context, v, _) => Text(format(v), style: style, maxLines: 1, overflow: TextOverflow.ellipsis),
    );
  }
}

/// A [Metric] whose value is a number that eases.
class EasedMetric extends StatelessWidget {
  const EasedMetric(this.label, this.value, {super.key, required this.format});
  final String label;
  final double? value;
  final String Function(double) format;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Semantics(
      label: label,
      value: value == null ? 'not measured' : format(value!),
      child: ExcludeSemantics(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label, style: NbType.text(NbSize.caption, c.muted, height: 1.3)),
            const SizedBox(height: 2),
            EasedNumber(value, format: format, style: NbType.data(NbSize.body, c.text, height: 1.2)),
          ],
        ),
      ),
    );
  }
}
