/// What every screen of the main window shares: the engine, the controllers, the window, and where you are.
library;

import 'package:flutter/widgets.dart';

import '../engine/engine_api.dart';
import '../platform/window.dart';
import '../state/search_controller.dart';
import '../state/settings_controller.dart';
import '../state/status_controller.dart';
import '../state/toast_controller.dart';

enum AppTab { search, indexing, settings }

enum SettingsPage {
  general('General'),
  indexing('Indexing'),
  models('Models'),
  performance('Performance'),
  privacy('Privacy'),
  about('About');

  const SettingsPage(this.label);
  final String label;
}

/// The open tab and Settings page (Ctrl+1/2/3 like 0.7.0).
class AppNav extends ChangeNotifier {
  AppTab _tab = AppTab.search;
  SettingsPage _page = SettingsPage.general;

  AppTab get tab => _tab;
  SettingsPage get page => _page;

  void go(AppTab t) {
    if (t == _tab) return;
    _tab = t;
    notifyListeners();
  }

  void openSettings(SettingsPage p) {
    _tab = AppTab.settings;
    _page = p;
    notifyListeners();
  }

  void showPage(SettingsPage p) {
    if (p == _page) return;
    _page = p;
    notifyListeners();
  }
}

class AppScope extends InheritedWidget {
  const AppScope({
    super.key,
    required super.child,
    required this.engine,
    required this.find,
    required this.status,
    required this.settings,
    required this.toasts,
    required this.nav,
    required this.window,
    required this.version,
  });

  final EngineApi engine;
  final FindController find;
  final StatusController status;
  final SettingsController settings;
  final ToastController toasts;
  final AppNav nav;
  final WindowControl window;
  final String version;

  static AppScope of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!;

  @override
  bool updateShouldNotify(AppScope old) => false; // the controllers notify their own listeners
}
