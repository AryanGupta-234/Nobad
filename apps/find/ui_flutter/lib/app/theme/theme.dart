/// The Material theme the few Material widgets (text fields, menus, dialogs) read, built from the NOBAD tokens.
library;

import 'package:material_ui/material_ui.dart';

import 'colors.dart';
import 'tokens.dart';
import 'typography.dart';

ThemeData nbTheme(NbColors c) {
  final scheme = ColorScheme(
    brightness: c.brightness,
    primary: c.orange,
    onPrimary: c.onOrange,
    secondary: c.orange,
    onSecondary: c.onOrange,
    error: c.danger,
    onError: c.onOrange,
    surface: c.surface,
    onSurface: c.text,
  );
  return ThemeData(
    brightness: c.brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: c.canvas,
    canvasColor: c.surface,
    fontFamily: NbFont.body,
    fontFamilyFallback: NbFont.bodyFallback,
    extensions: [c],
    splashFactory: NoSplash.splashFactory,
    highlightColor: c.orangeA(.08),
    hoverColor: c.orangeA(.06),
    focusColor: c.orangeA(.14),
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: c.orange,
      selectionColor: c.orangeA(.38),
      selectionHandleColor: c.orange,
    ),
    scrollbarTheme: ScrollbarThemeData(
      thumbColor: WidgetStatePropertyAll(c.line2),
      thickness: const WidgetStatePropertyAll(6),
      radius: const Radius.circular(3),
      crossAxisMargin: 2,
    ),
    tooltipTheme: TooltipThemeData(
      waitDuration: const Duration(milliseconds: 500),
      textStyle: NbType.text(NbSize.small, c.text),
      decoration: BoxDecoration(
        color: c.raised,
        border: Border.all(color: c.line2),
        borderRadius: NbRadius.controlAll,
      ),
    ),
    menuTheme: MenuThemeData(
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(c.surface),
        surfaceTintColor: const WidgetStatePropertyAll(Color(0x00000000)),
        shadowColor: WidgetStatePropertyAll(c.shadow),
        elevation: const WidgetStatePropertyAll(12),
        padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(vertical: NbSpace.x1)),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(
            borderRadius: NbRadius.rowAll,
            side: BorderSide(color: c.line2),
          ),
        ),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: c.surface,
      surfaceTintColor: const Color(0x00000000),
      barrierColor: c.isDark ? const Color(0xB3000000) : const Color(0x66000000),
      shape: RoundedRectangleBorder(
        borderRadius: NbRadius.panelAll,
        side: BorderSide(color: c.line2),
      ),
    ),
  );
}
