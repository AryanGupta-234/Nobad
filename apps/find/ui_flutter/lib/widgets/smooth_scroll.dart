/// Smooth mouse-wheel scrolling. Flutter on Windows jumps a whole wheel notch at once, which reads as stutter;
/// here each notch glides (220 ms, ease out) and quick notches add up to one continuous glide toward the
/// combined target. Touchpads, drags, the keyboard and the scrollbar keep their own behaviour. With Windows'
/// "Animation effects" off, wheel steps jump as before.
///
/// Use [SmoothScroll] where you'd build a scroll view, or give a list a [SmoothScrollController] you own.
library;

import 'package:flutter/widgets.dart';

class SmoothScrollController extends ScrollController {
  SmoothScrollController({super.initialScrollOffset, super.keepScrollOffset, super.debugLabel});

  /// Off: wheel notches jump (reduced motion).
  bool glide = true;

  @override
  ScrollPosition createScrollPosition(ScrollPhysics physics, ScrollContext context, ScrollPosition? oldPosition) =>
      _SmoothPosition(
        this,
        physics: physics,
        context: context,
        initialPixels: initialScrollOffset,
        keepScrollOffset: keepScrollOffset,
        oldPosition: oldPosition,
        debugLabel: debugLabel,
      );
}

class _SmoothPosition extends ScrollPositionWithSingleContext {
  _SmoothPosition(
    this.owner, {
    required super.physics,
    required super.context,
    super.initialPixels,
    super.keepScrollOffset,
    super.oldPosition,
    super.debugLabel,
  });

  final SmoothScrollController owner;
  double? _target;

  static const glideTime = Duration(milliseconds: 220);

  @override
  void pointerScroll(double delta) {
    if (delta == 0 || !owner.glide || !hasContentDimensions) {
      _target = null;
      super.pointerScroll(delta);
      return;
    }
    // keep adding to where the glide is going, so fast notches don't lose distance
    final from = _target != null && isScrollingNotifier.value ? _target! : pixels;
    final to = (from + delta).clamp(minScrollExtent, maxScrollExtent).toDouble();
    _target = to;
    if (to == pixels) return;
    animateTo(to, duration: glideTime, curve: Curves.easeOutCubic).whenComplete(() {
      if (_target == to) _target = null;
    });
  }

  @override
  void jumpTo(double value) {
    _target = null;
    super.jumpTo(value);
  }
}

/// Owns a [SmoothScrollController] for one scroll view: `SmoothScroll(builder: (c) => ListView(controller: c, ...))`.
class SmoothScroll extends StatefulWidget {
  const SmoothScroll({super.key, required this.builder});
  final Widget Function(ScrollController controller) builder;

  @override
  State<SmoothScroll> createState() => _SmoothScrollState();
}

class _SmoothScrollState extends State<SmoothScroll> {
  final _c = SmoothScrollController();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _c.glide = !(MediaQuery.maybeDisableAnimationsOf(context) ?? false);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(_c);
}
