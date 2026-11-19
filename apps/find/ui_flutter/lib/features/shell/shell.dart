/// The main window: the rail on the left, the open page, the toast, and over them the splash (while the engine
/// connects) and the first-run welcome.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/tokens.dart';
import '../../engine/engine_api.dart';
import '../../engine/events.dart';
import '../../platform/demo.dart';
import '../../widgets/glass.dart';
import '../../widgets/panels.dart';
import '../indexing/indexing_screen.dart';
import '../search/search_screen.dart';
import '../settings/settings_screen.dart';
import '../splash/splash.dart';
import '../welcome/welcome.dart';
import 'rail.dart';

class Shell extends StatefulWidget {
  const Shell({super.key, this.splash = true, this.demo});
  final bool splash;
  final Demo? demo;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  StreamSubscription<EngineEvent>? _shows;
  bool _splashDone = false;
  AppScope? _scope;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (_scope != null) return; // once: the scope is rebuilt with the app, its controllers stay the same
    _scope = s;
    _shows?.cancel();
    _shows = s.engine.events.listen((e) {
      if (e is ShowEvent && e.what == 'main') {
        final t = e.text;
        if (t != null) s.find.handOver(t); // kept until the search screen takes it
        s.window.front();
        unawaited(s.engine.uiShown('main').catchError((Object _) {})); // the engine starts idle until a window shows
        s.nav.go(AppTab.search);
        unawaited(s.find.loadHere());
      }
      if (e is QuittingEvent) s.window.close(); // the engine is ending: this window goes with it
    });
    _splashDone = !widget.splash || s.engine.link.value != Link.connecting;
    if (!_splashDone) s.engine.link.addListener(_linkChanged);
    unawaited(s.find.loadHere());
    widget.demo?.start(s);
  }

  void _linkChanged() {
    final s = _scope!;
    if (s.engine.link.value == Link.connecting) return;
    s.engine.link.removeListener(_linkChanged);
    if (mounted) setState(() => _splashDone = true);
  }

  @override
  void dispose() {
    _shows?.cancel();
    _scope?.engine.link.removeListener(_linkChanged);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    return ColoredBox(
      color: const Color(0x00000000),
      child: Stack(
        children: [
          const Positioned.fill(child: Backdrop()), // painted once; Mica shows through it
          Positioned.fill(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Rail(),
                Expanded(
                  child: ListenableBuilder(
                    listenable: s.nav,
                    builder: (context, _) => AnimatedSwitcher(
                      duration: NbMotion.of(context, NbMotion.base),
                      switchInCurve: NbMotion.curve,
                      transitionBuilder: (child, a) => FadeTransition(
                        opacity: a,
                        child: SlideTransition(
                          position: Tween(begin: const Offset(0, .012), end: Offset.zero).animate(a),
                          child: child,
                        ),
                      ),
                      child: switch (s.nav.tab) {
                        AppTab.search => const SearchScreen(key: ValueKey('search')),
                        AppTab.indexing => const IndexingScreen(key: ValueKey('index')),
                        AppTab.settings => const SettingsScreen(key: ValueKey('settings')),
                      },
                    ),
                  ),
                ),
              ],
            ),
          ),
          Positioned(
            left: Rail.room,
            right: 0,
            bottom: 52,
            child: Center(child: ToastHost(toasts: s.toasts)),
          ),
          ListenableBuilder(
            listenable: s.settings,
            builder: (context, _) => s.settings.loaded && !s.settings.settings.flag('welcome_seen')
                ? const Positioned.fill(child: Welcome())
                : const SizedBox.shrink(),
          ),
          Positioned.fill(
            child: IgnorePointer(
              ignoring: _splashDone,
              child: AnimatedSwitcher(
                duration: NbMotion.of(context, NbMotion.slow),
                child: _splashDone ? const SizedBox.expand() : const Splash(),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
