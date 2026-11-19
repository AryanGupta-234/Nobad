/// The splash while NOBAD VPN's window starts: the mark and the name over the map, the daylight sweeping in, and a
/// thin line that moves with what really happens: the window is up, the engine's pipe answers, the first state
/// arrives. It ends as soon as there's a state to show (or after 4 s without an engine: the window then says
/// NOBAD isn't running). With Windows' animation effects off, nothing sweeps: the steps just appear.
library;

import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../map/world_map.dart';
import '../../state/vpn_controller.dart';
import '../../widgets/panels.dart';

class Splash extends StatefulWidget {
  const Splash({super.key, required this.vpn, required this.onDone, this.giveUp = const Duration(seconds: 4)});
  final VpnController vpn;
  final VoidCallback onDone;
  final Duration giveUp;
  @override
  State<Splash> createState() => _SplashState();
}

/// The steps, in order, with the words under the line.
(double, String) splashStep(Link link, bool hasState) => hasState
    ? (1, 'Ready')
    : switch (link) {
        Link.connected => (.75, 'Reading the protection state…'),
        Link.connecting => (.35, 'Connecting to the NOBAD VPN engine…'),
        _ => (.2, "Waiting for NOBAD VPN…"),
      };

class _SplashState extends State<Splash> with SingleTickerProviderStateMixin {
  late final _sweep = AnimationController(vsync: this, duration: const Duration(milliseconds: 1400));
  Timer? _giveUp, _end;
  var _fading = false;

  @override
  void initState() {
    super.initState();
    widget.vpn.addListener(_check);
    _giveUp = Timer(widget.giveUp, _finish);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (MediaQuery.maybeDisableAnimationsOf(context) ?? false) {
        _sweep.value = 1;
      } else {
        _sweep.forward();
      }
      _check();
    });
  }

  void _check() {
    if (widget.vpn.state != null) {
      // let the line reach its end and the daylight settle before handing over
      _end ??= Timer(Duration(milliseconds: _sweep.isCompleted ? 250 : 700), _finish);
    }
    if (mounted) setState(() {});
  }

  void _finish() {
    if (_fading || !mounted) return;
    setState(() => _fading = true);
    Timer(NbMotion.of(context, NbMotion.slow), widget.onDone);
  }

  @override
  void dispose() {
    widget.vpn.removeListener(_check);
    _giveUp?.cancel();
    _end?.cancel();
    _sweep.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final (progress, words) = splashStep(widget.vpn.link, widget.vpn.state != null);
    return AnimatedOpacity(
      opacity: _fading ? 0 : 1,
      duration: NbMotion.of(context, NbMotion.slow),
      child: Stack(
        children: [
          Positioned.fill(
            child: ColoredBox(color: c.canvas.withValues(alpha: c.isDark ? .55 : .5)),
          ),
          Positioned.fill(
            child: AnimatedBuilder(
              animation: _sweep,
              builder: (context, _) => WorldMap(sweep: Curves.easeOutCubic.transform(_sweep.value)),
            ),
          ),
          Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const NbMark(size: 56),
                const SizedBox(height: NbSpace.x3),
                Text('NOBAD VPN', style: NbType.display(NbSize.page, c.text)),
                const SizedBox(height: 6),
                Text('Software with a point of view.', style: NbType.text(NbSize.small, c.muted)),
                const SizedBox(height: NbSpace.x4),
                Semantics(
                  label: words,
                  value: '${(progress * 100).round()} percent',
                  child: SizedBox(
                    width: 220,
                    height: 2,
                    child: Stack(
                      children: [
                        Positioned.fill(child: ColoredBox(color: c.line2)),
                        TweenAnimationBuilder<double>(
                          tween: Tween(end: progress),
                          duration: NbMotion.of(context, const Duration(milliseconds: 450)),
                          curve: NbMotion.curve,
                          builder: (context, v, _) => FractionallySizedBox(
                            widthFactor: v,
                            child: DecoratedBox(
                              decoration: BoxDecoration(
                                color: c.orange,
                                boxShadow: [BoxShadow(color: c.orangeA(.6), blurRadius: 8)],
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: NbSpace.x2),
                Text(words, style: NbType.text(NbSize.caption, c.dim)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
