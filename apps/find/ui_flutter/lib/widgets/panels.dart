/// Surfaces and read-outs: panels, page and section titles, stat tiles, meters, notices, the toast.
library;

import 'package:flutter/widgets.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import '../state/toast_controller.dart';
import 'controls.dart';
import 'glass.dart';

/// A grouped surface. [live] gives it the orange edge (the thing that's working now).
class NbPanel extends StatelessWidget {
  const NbPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(NbSpace.x4),
    this.live = false,
    this.clip = false,
  });
  final Widget child;
  final EdgeInsetsGeometry padding;
  final bool live;
  final bool clip;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    // a card of frosted glass on the backdrop (no blur: fill and rim)
    return Glass(
      radius: 8,
      padding: padding,
      rim: live ? c.orangeA(.55) : null,
      child: clip ? ClipRSuperellipse(borderRadius: BorderRadius.circular(8), child: child) : child,
    );
  }
}

/// The one display line of a page ("INDEX", "SETTINGS"), with the orange rule under it.
class PageTitle extends StatelessWidget {
  const PageTitle(this.text, {super.key, this.size = NbSize.page});
  final String text;
  final double size;

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
          const SignalRule(),
        ],
      ),
    );
  }
}

/// The short orange line with its glow: the NOBAD signal under a display heading.
class SignalRule extends StatelessWidget {
  const SignalRule({super.key, this.width = 46});
  final double width;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      width: width,
      height: 3,
      decoration: BoxDecoration(
        color: c.orange,
        boxShadow: [if (c.isDark) BoxShadow(color: c.orangeA(.9), blurRadius: 14)],
      ),
    );
  }
}

/// A section heading inside a page: sentence case, quiet, with an optional line of help after it.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing, this.top = NbSpace.x5});
  final String text;
  final Widget? trailing;
  final double top;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: EdgeInsets.only(top: top, bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(left: 2),
              child: Semantics(header: true, child: Text(text, style: sectionStyle(c))),
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}

/// The one section-header style: Settings groups, Index sections, Home's lists.
TextStyle sectionStyle(NbColors c) => NbType.text(NbSize.small, c.dim, weight: FontWeight.w600, height: 1.3);

/// Every page's header: where you are ([crumb], small), the page's one display line, and actions on the right.
/// It sits on the page gutter; the page's toolbar and content start on the same left line under it.
class PageHeader extends StatelessWidget {
  const PageHeader(this.title, {super.key, this.crumb, this.trailing});
  final String title;
  final String? crumb;
  final Widget? trailing;

  static const padding = EdgeInsets.fromLTRB(NbSpace.gutter, 14, NbSpace.gutter, 12);

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: padding,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (crumb != null) ...[
                  Text(crumb!, style: NbType.text(NbSize.small, c.dim, weight: FontWeight.w600)),
                  const SizedBox(height: 3),
                ],
                PageTitle(title),
              ],
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}

/// A number with what it is: "186 MB" over "Memory".
class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.value, required this.label, this.live = false});
  final String value;
  final String label;
  final bool live;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return NbPanel(
      padding: const EdgeInsets.fromLTRB(12, 9, 12, 9),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            value,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            // a number reads as data; a long name (a graphics card) reads better as text
            style: value.length > 12
                ? NbType.text(13.5, live ? c.orange : c.text, weight: FontWeight.w600, height: 1.3)
                : NbType.data(16, live ? c.orange : c.text, weight: FontWeight.w600, height: 1.25),
          ),
          const SizedBox(height: 2),
          Text(
            label,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: NbType.text(NbSize.small, c.dim, height: 1.35),
          ),
        ],
      ),
    );
  }
}

/// A grid of tiles that fills the width with as many columns of at least [min] as fit.
class TileGrid extends StatelessWidget {
  const TileGrid({super.key, required this.children, this.min = 170, this.gap = 10});
  final List<Widget> children;
  final double min;
  final double gap;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, box) {
      final cols = ((box.maxWidth + gap) / (min + gap)).floor().clamp(1, 8);
      final w = (box.maxWidth - gap * (cols - 1)) / cols;
      return Wrap(
        spacing: gap,
        runSpacing: gap,
        children: [for (final ch in children) SizedBox(width: w, child: ch)],
      );
    },
  );
}

/// A progress bar. [busy]: working with no known end (watching for changes, counting): a still, softly tinted
/// track rather than an endless animation, which would keep the window drawing for nothing.
class NbMeter extends StatelessWidget {
  const NbMeter({super.key, required this.fraction, this.busy = false, this.muted = false});
  final double fraction;
  final bool busy;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final fill = muted ? c.dim : c.orange;
    return Semantics(
      value: busy ? 'working' : '${(fraction * 100).round()}%',
      child: SizedBox(
        height: 6,
        child: ClipRRect(
          borderRadius: NbRadius.pillAll,
          child: ColoredBox(
            color: c.raised,
            child: busy
                ? ColoredBox(color: fill.withValues(alpha: .35), child: const SizedBox.expand())
                : TweenAnimationBuilder<double>(
                    tween: Tween(end: fraction.clamp(0, 1).toDouble()),
                    duration: NbMotion.of(context, NbMotion.slow),
                    curve: NbMotion.curve,
                    builder: (context, f, _) => FractionallySizedBox(
                      alignment: Alignment.centerLeft,
                      widthFactor: f,
                      child: ColoredBox(color: fill),
                    ),
                  ),
          ),
        ),
      ),
    );
  }
}

/// A one-time notice with its action ("Got it"): an orange edge on the left, never a modal.
class NoticeBar extends StatelessWidget {
  const NoticeBar({super.key, required this.text, required this.action, required this.onAction});
  final String text;
  final String action;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: c.panel,
        borderRadius: NbRadius.rowAll,
        border: Border.all(color: c.line2),
      ),
      child: Stack(
        children: [
          Positioned(left: 0, top: 0, bottom: 0, width: 3, child: ColoredBox(color: c.orange)),
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 10, 10, 10),
            child: Row(
              children: [
                Expanded(child: Text(text, style: NbType.text(13, c.muted, height: 1.5))),
                const SizedBox(width: NbSpace.x3),
                NbButton(action, kind: NbButtonKind.ghost, small: true, onPressed: onAction),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// The toast: slides up from the bottom edge, one at a time, announced to screen readers.
class ToastHost extends StatelessWidget {
  const ToastHost({super.key, required this.toasts});
  final ToastController toasts;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: toasts,
      builder: (context, _) {
        final m = toasts.message;
        return IgnorePointer(
          ignoring: m == null,
          child: AnimatedSlide(
            offset: m == null ? const Offset(0, 1.6) : Offset.zero,
            duration: NbMotion.of(context, NbMotion.slow),
            curve: NbMotion.curve,
            child: AnimatedOpacity(
              opacity: m == null ? 0 : 1,
              duration: NbMotion.of(context, NbMotion.base),
              child: Semantics(
                liveRegion: true,
                child: Container(
                  key: ValueKey(toasts.serial),
                  constraints: const BoxConstraints(maxWidth: 560),
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
                  decoration: BoxDecoration(
                    color: c.surface,
                    border: Border.all(color: c.orangeA(.5)),
                    borderRadius: NbRadius.rowAll,
                    boxShadow: [
                      BoxShadow(
                        color: c.shadow.withValues(alpha: .5),
                        blurRadius: 40,
                        offset: const Offset(0, 16),
                        spreadRadius: -14,
                      ),
                    ],
                  ),
                  child: Text(m ?? '', style: NbType.text(13.5, c.text, height: 1.4)),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
