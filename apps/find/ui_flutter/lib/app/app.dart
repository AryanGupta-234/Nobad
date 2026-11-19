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
  const NobadFindApp({super.key, required this.engine, this.mode = AppMode.main, this.window = const NoWindow(),
      this.demo, this.splash = true});
  final EngineApi engine;
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

  @override
  void initState() {
    super.initState();
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

  @override
  void dispose() {
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
              child: DefaultTextStyle(style: TextStyle(color: c.text, fontSize: 14), child: child!),
            ),
          ),
          home: Material(
            type: MaterialType.transparency,
            child: bar
                ? BarWindow(engine: widget.engine, window: widget.window, demo: widget.demo)
                : _Keys(nav: nav, child: Shell(splash: widget.splash, demo: widget.demo)),
          ),
        );
      },
    );
  }
}

/// Ctrl+1 / Ctrl+2 / Ctrl+3: Search, Index, Settings (0.7.0).
class _Keys extends StatelessWidget {
  const _Keys({required this.nav, required this.child});
  final AppNav nav;
  final Widget child;

  @override
  Widget build(BuildContext context) => CallbackShortcuts(
        bindings: {
          const SingleActivator(LogicalKeyboardKey.digit1, control: true): () => nav.go(AppTab.search),
          const SingleActivator(LogicalKeyboardKey.digit2, control: true): () => nav.go(AppTab.indexing),
          const SingleActivator(LogicalKeyboardKey.digit3, control: true): () => nav.go(AppTab.settings),
        },
        child: child,
      );
}
