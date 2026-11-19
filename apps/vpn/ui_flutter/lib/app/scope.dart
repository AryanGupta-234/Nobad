/// What every screen reaches: the engine, the controller, the window, and where the main window is.
library;

import 'package:flutter/widgets.dart';

import '../engine/engine.dart';
import '../platform/files.dart';
import '../platform/window.dart';
import '../state/vpn_controller.dart';

/// The rail's screens, in order (Ctrl+1 .. Ctrl+8).
enum AppTab { home, servers, speed, network, intel, streaming, activity, settings }

class AppNav extends ValueNotifier<AppTab> {
  AppNav([super.initial = AppTab.home]);
  void go(AppTab t) => value = t;

  /// A question from the command palette for the screen it opens: ('investigate', site) or ('watch', title).
  (String, String)? ask;

  void goAsk(AppTab t, String kind, String q) {
    ask = (kind, q);
    if (value == t) {
      notifyListeners();
    } else {
      value = t;
    }
  }

  /// The pending question of [kind], taken once.
  String? takeAsk(String kind) {
    final a = ask;
    if (a == null || a.$1 != kind) return null;
    ask = null;
    return a.$2;
  }
}

class AppScope extends InheritedWidget {
  const AppScope({
    super.key,
    required this.engine,
    required this.vpn,
    required this.window,
    required this.nav,
    required this.files,
    this.now,
    required super.child,
  });

  /// The clock for the map's daylight (tests fix it).
  final DateTime Function()? now;
  final EngineApi engine;
  final VpnController vpn;
  final WindowControl window;
  final AppNav nav;
  final FilePicker files;

  static AppScope of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!;

  @override
  bool updateShouldNotify(AppScope old) =>
      old.engine != engine || old.vpn != vpn || old.window != window || old.nav != nav || old.files != files;
}

/// For dialogs: the navigator's context sits above AppScope (MaterialApp.builder wraps it), so dialogs re-provide it.
final appNavigator = GlobalKey<NavigatorState>();

/// The whole window's picture (goldens, screenshots).
final shotBoundary = GlobalKey();
