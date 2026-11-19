/// The app: theme (dark or light from the engine's setting, glass when Windows takes it), the controller, and either
/// the main window or the tray pop-up.
library;

import 'dart:async';
import 'dart:ui' show AppExitResponse;

import 'package:material_ui/material_ui.dart';

import '../engine/engine.dart';
import '../features/mini/mini_window.dart';
import '../features/shell/shell.dart';
import '../platform/files.dart';
import '../platform/window.dart';
import '../state/vpn_controller.dart';
import 'scope.dart';
import 'theme/colors.dart';
import 'theme/theme.dart';

enum AppMode { main, mini }

const appVersion = '2.0.0';

class NobadVpnApp extends StatefulWidget {
  const NobadVpnApp({
    super.key,
    required this.engine,
    this.mode = AppMode.main,
    this.window = const NoWindow(),
    this.files = const NoFilePicker(),
    this.reduceMotion,
    this.tab = AppTab.home,
    this.splash = true,
    this.now,
  });

  /// The start-up splash (tests turn it off).
  final bool splash;

  /// The clock for the map (tests and goldens fix it).
  final DateTime Function()? now;

  /// The screen the main window opens on (NOBAD_VPN_UI_TAB, for screenshots).
  final AppTab tab;
  final EngineApi engine;
  final AppMode mode;
  final WindowControl window;
  final FilePicker files;

  /// Animations off: Windows' "Animation effects" switch (read at start and when the window comes back), or tests.
  final bool? reduceMotion;

  @override
  State<NobadVpnApp> createState() => NobadVpnAppState();
}

class NobadVpnAppState extends State<NobadVpnApp> {
  final _mini = GlobalKey<MiniWindowState>();
  late final vpn = VpnController(widget.engine, onShow: _show, onQuitting: widget.window.close);
  late final nav = AppNav(widget.tab);
  bool _glass = false;
  bool? _appliedDark;
  late bool _motionOff = widget.reduceMotion ?? systemAnimationsOff();

  /// On screen and not minimized: animations only run while it is.
  bool _onScreen = true;
  late final AppLifecycleListener _life;

  bool get _isMini => widget.mode == AppMode.mini;

  @override
  void initState() {
    super.initState();
    _life = AppLifecycleListener(onStateChange: _lifecycle, onExitRequested: _exit);
    vpn.addListener(_restyle);
    WidgetsBinding.instance.addPostFrameCallback((_) => _restyle(force: true));
  }

  void _show(String window) {
    if (_isMini && window == 'mini') {
      _mini.currentState?.toggle();
    } else if (!_isMini && window == 'main') {
      widget.window.front();
      unawaited(widget.engine.shown(true));
    }
  }

  /// The main window closes: with the tray icon and "close to tray" on, NOBAD keeps running there (only this
  /// window ends); otherwise closing the window quits NOBAD, as the classic window did. The VPN stays on either way.
  Future<AppExitResponse> _exit() async {
    final s = vpn.state;
    if (!_isMini && s != null && !(s.setting('close_to_tray') && s.tray)) {
      try {
        await widget.engine.quit().timeout(const Duration(seconds: 2));
      } on Object {
        // the engine is gone already
      }
    }
    return AppExitResponse.exit;
  }

  void _restyle({bool force = false}) {
    final dark = vpn.state?.dark ?? true;
    if (!force && dark == _appliedDark) return;
    _appliedDark = dark;
    final base = dark ? NbColors.dark : NbColors.light;
    final took = widget.window.look(dark: dark, glass: true, canvasRgb: base.bg.toARGB32() & 0xFFFFFF);
    if (mounted) setState(() => _glass = took);
  }

  void _lifecycle(AppLifecycleState state) {
    final on = state == AppLifecycleState.resumed || state == AppLifecycleState.inactive;
    if (on == _onScreen) return;
    if (!_isMini) unawaited(widget.engine.shown(on));
    setState(() {
      _onScreen = on;
      if (on && widget.reduceMotion == null) _motionOff = systemAnimationsOff();
    });
  }

  @override
  void dispose() {
    _life.dispose();
    vpn.removeListener(_restyle);
    vpn.dispose();
    nav.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: vpn,
      builder: (context, _) {
        final dark = vpn.state?.dark ?? true;
        final c = (dark ? NbColors.dark : NbColors.light).withGlass(_glass);
        return MaterialApp(
          title: _isMini ? 'NOBAD VPN quick view' : 'NOBAD VPN',
          debugShowCheckedModeBanner: false,
          theme: nbTheme(c),
          themeAnimationDuration: const Duration(milliseconds: 180),
          color: c.orange,
          navigatorKey: appNavigator,
          builder: (context, child) => RepaintBoundary(
            key: shotBoundary,
            child: AppScope(
              engine: widget.engine,
              vpn: vpn,
              window: widget.window,
              nav: nav,
              files: widget.files,
              now: widget.now,
              child: MediaQuery(
                data: MediaQuery.of(context).copyWith(disableAnimations: _motionOff),
                child: TickerMode(
                  enabled: _onScreen,
                  child: DefaultTextStyle(style: TextStyle(color: c.text, fontSize: 14), child: child!),
                ),
              ),
            ),
          ),
          home: Material(
            type: MaterialType.transparency,
            child: _isMini ? MiniWindow(key: _mini) : Shell(version: appVersion, splash: widget.splash, now: widget.now),
          ),
        );
      },
    );
  }
}
