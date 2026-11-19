/// The app: theme (dark/light from the setting, glass when Windows takes it), the controllers, and either the
/// main window (splash → first-run welcome → rail + Search / Index / Settings) or the quick find bar.
library;

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../engine/engine_api.dart';
import '../features/bar/bar_window.dart';
import '../features/shell/shell.dart';
import '../platform/demo.dart';
import '../platform/window.dart';
import '../state/search_controller.dart';
import '../state/settings_controller.dart';
import '../state/status_controller.dart';
import '../state/toast_controller.dart';
import 'scope.dart';
import 'theme/colors.dart';
import 'theme/theme.dart';

enum AppMode { main, bar }

const appVersion = '0.8.0';

class NobadFindApp extends StatefulWidget {
  const NobadFindApp({
    super.key,
    required this.engine,
    this.mode = AppMode.main,
    this.window = const NoWindow(),
    this.demo,
    this.splash = true,
    this.reduceMotion,
  });
  final EngineApi engine;

  /// Animations off: Windows' "Animation effects" switch (read at start and when the window comes back), or
  /// forced by tests.
  final bool? reduceMotion;
  final AppMode mode;
  final WindowControl window;
  final Demo? demo;

  /// Show the splash while the engine connects (tests turn it off).
  final bool splash;

  @override
  State<NobadFindApp> createState() => _NobadFindAppState();
}

class _NobadFindAppState extends State<NobadFindApp> {
  late final toasts = ToastController(engine: widget.engine);
  late final settings = SettingsController(widget.engine, toasts: toasts);
  late final status = StatusController(widget.engine);
  late final find = FindController(widget.engine, toasts: toasts);
  final nav = AppNav();
  bool _glass = false;
  (bool, bool)? _applied;
  late bool _motionOff = widget.reduceMotion ?? systemAnimationsOff();

  /// On screen (not hidden or minimized): animations only run while it is.
  bool _onScreen = true;
  late final AppLifecycleListener _life;

  String get _windowName => widget.mode == AppMode.bar ? 'bar' : 'main';

  @override
  void initState() {
    super.initState();
    _life = AppLifecycleListener(onStateChange: _lifecycle);
    settings.addListener(_restyle);
    unawaited(settings.load());
    widget.engine.link.addListener(_relink);
    WidgetsBinding.instance.addPostFrameCallback((_) => _restyle());
  }

  /// Settings come back with the engine (it may start after the window).
  void _relink() {
    if (widget.engine.link.value == Link.connected) unawaited(settings.load());
  }

  void _restyle() {
    final s = settings.settings;
    final want = (s.dark, s.glass);
    if (want == _applied) return;
    _applied = want;
    final base = s.dark ? NbColors.dark : NbColors.light;
    final took = widget.window.look(dark: s.dark, glass: s.glass, canvasRgb: base.bg.toARGB32() & 0xFFFFFF);
    setState(() => _glass = took);
  }

  /// Minimized or hidden: tell the engine (it stops indexing when the main window goes, unless asked to keep on)
  /// and stop every animation; back on screen: the same the other way, and look at the animation setting again.
  void _lifecycle(AppLifecycleState state) {
    final on = state == AppLifecycleState.resumed || state == AppLifecycleState.inactive;
    if (on == _onScreen) return;
    if (widget.mode == AppMode.main) {
      final f = on ? widget.engine.uiShown(_windowName) : widget.engine.uiHidden(_windowName);
      unawaited(f.catchError((Object _) {}));
    }
    setState(() {
      _onScreen = on;
      if (on && widget.reduceMotion == null) _motionOff = systemAnimationsOff();
    });
  }

  @override
  void dispose() {
    _life.dispose();
    settings.removeListener(_restyle);
    widget.engine.link.removeListener(_relink);
    find.dispose();
    status.dispose();
    settings.dispose();
    toasts.dispose();
    nav.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: settings,
      builder: (context, _) {
        final c = (settings.settings.dark ? NbColors.dark : NbColors.light).withGlass(_glass);
        final bar = widget.mode == AppMode.bar;
        return MaterialApp(
          title: bar ? 'NOBAD Find bar' : 'NOBAD Find',
          debugShowCheckedModeBanner: false,
          theme: nbTheme(c),
          themeAnimationDuration: const Duration(milliseconds: 180),
          color: c.orange,
          navigatorKey: appNavigator,
          builder: (context, child) => RepaintBoundary(
            key: shotBoundary,
            child: AppScope(
              engine: widget.engine,
              find: find,
              status: status,
              settings: settings,
              toasts: toasts,
              nav: nav,
              window: widget.window,
              version: appVersion,
              child: MediaQuery(
                data: MediaQuery.of(context).copyWith(disableAnimations: _motionOff),
                child: TickerMode(
                  enabled: _onScreen,
                  child: DefaultTextStyle(
                    style: TextStyle(color: c.text, fontSize: 14),
                    child: child!,
                  ),
                ),
              ),
            ),
          ),
          home: Material(
            type: MaterialType.transparency,
            child: bar
                ? BarWindow(engine: widget.engine, window: widget.window, demo: widget.demo)
                : _Keys(
                    nav: nav,
                    window: widget.window,
                    engine: widget.engine,
                    child: Shell(splash: widget.splash, demo: widget.demo),
                  ),
          ),
        );
      },
    );
  }
}

/// Window-wide keys: Ctrl+1 / Ctrl+2 / Ctrl+3 for Search, Index, Settings; Esc on Index and Settings hides the
/// window (0.7.0). Holds the keyboard focus when a page has nothing focused, so the keys always work.
class _Keys extends StatefulWidget {
  const _Keys({required this.nav, required this.window, required this.engine, required this.child});
  final AppNav nav;
  final WindowControl window;
  final EngineApi engine;
  final Widget child;

  @override
  State<_Keys> createState() => _KeysState();
}

class _KeysState extends State<_Keys> {
  final _focus = FocusNode(debugLabel: 'window keys');

  @override
  void initState() {
    super.initState();
    widget.nav.addListener(_moved);
  }

  /// Search focuses its own box; the other pages start with the window keys focused.
  void _moved() => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (mounted && widget.nav.tab != AppTab.search) _focus.requestFocus();
  });

  @override
  void dispose() {
    widget.nav.removeListener(_moved);
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CallbackShortcuts(
    bindings: {
      const SingleActivator(LogicalKeyboardKey.digit1, control: true): () => widget.nav.go(AppTab.search),
      const SingleActivator(LogicalKeyboardKey.digit2, control: true): () => widget.nav.go(AppTab.indexing),
      const SingleActivator(LogicalKeyboardKey.digit3, control: true): () => widget.nav.go(AppTab.settings),
      const SingleActivator(LogicalKeyboardKey.escape): () {
        if (widget.nav.tab == AppTab.search) return;
        widget.window.hide();
        unawaited(widget.engine.uiHidden('main').catchError((Object _) {}));
      },
    },
    child: Focus(focusNode: _focus, child: widget.child),
  );
}
