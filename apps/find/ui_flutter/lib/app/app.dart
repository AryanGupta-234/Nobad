/// The app shell: dark NOBAD theme, and either the main search window or the quick find bar.
library;

import 'package:material_ui/material_ui.dart';

import '../engine/rpc.dart';
import '../features/bar/bar_window.dart';
import '../features/search/search_screen.dart';
import '../platform/window.dart';
import 'theme/colors.dart';
import 'theme/typography.dart';

enum AppMode { main, bar }

const appVersion = '0.8.0-proto';

class NobadFindApp extends StatelessWidget {
  const NobadFindApp({super.key, required this.engine, this.mode = AppMode.main, this.window = const NoWindow()});
  final Engine engine;
  final AppMode mode;
  final WindowControl window;

  static ThemeData theme() => ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: Nb.bg,
        canvasColor: Nb.bg,
        fontFamily: NbType.body,
        fontFamilyFallback: NbType.bodyFallback,
        colorScheme: const ColorScheme.dark(primary: Nb.orange, secondary: Nb.orange, surface: Nb.bg, onSurface: Nb.text),
        textSelectionTheme: TextSelectionThemeData(
            cursorColor: Nb.orange, selectionColor: Nb.orangeA(.45), selectionHandleColor: Nb.orange),
        scrollbarTheme: ScrollbarThemeData(
          thumbColor: WidgetStateProperty.all(Nb.line2),
          thickness: WidgetStateProperty.all(6),
          radius: const Radius.circular(3),
        ),
        splashFactory: NoSplash.splashFactory,
      );

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: mode == AppMode.bar ? 'NOBAD Find bar' : 'NOBAD Find',
        debugShowCheckedModeBanner: false,
        theme: theme(),
        color: Nb.orange,
        home: Material(
          type: MaterialType.transparency,
          child: mode == AppMode.bar
              ? BarWindow(engine: engine, window: window)
              : SearchScreen(engine: engine, window: window, version: appVersion),
        ),
      );
}
