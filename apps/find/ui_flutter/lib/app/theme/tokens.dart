/// Spacing, radius and motion tokens.
///
/// Radius follows hierarchy, not one value for everything: key caps and chips are small, controls and rows are
/// medium, panels are large, and pills are only for things you can toggle or that name a filter.
library;

import 'package:flutter/widgets.dart';

abstract final class NbSpace {
  static const x1 = 4.0;
  static const x2 = 8.0;
  static const x3 = 12.0;
  static const x4 = 16.0;
  static const x5 = 20.0;
  static const x6 = 24.0;
  static const x8 = 32.0;
  static const x10 = 40.0;
  static const x14 = 56.0;

  /// Reading width of a page column (Settings, Index): content stays top-left at this width, the rest of the
  /// window shows the map behind it.
  static const column = 760.0;

  /// The widest the results area gets.
  static const maxContent = 1040.0; // 0.8.5: the search bar and results never stretch very wide

  /// Every page's left and right gutter: its header, toolbar and content start on the same line.
  static const gutter = 20.0;

  /// The sidebar: 200 px with 32 px items.
  static const sidebar = 200.0;

  /// Content width (the window less the sidebar, so a window of about 1090 px) from which the search shows the
  /// detail pane and Index becomes two columns.
  static const wide = 880.0;
}

abstract final class NbRadius {
  static const key = Radius.circular(6);
  static const control = Radius.circular(10);
  static const row = Radius.circular(12);
  static const panel = Radius.circular(18);
  static const pill = Radius.circular(999);

  static const keyAll = BorderRadius.all(key);
  static const controlAll = BorderRadius.all(control);
  static const rowAll = BorderRadius.all(row);
  static const panelAll = BorderRadius.all(panel);
  static const pillAll = BorderRadius.all(pill);
}

abstract final class NbMotion {
  /// app.css cubic-bezier(.2, .7, .2, 1): quick out, long settle.
  static const curve = Cubic(.2, .7, .2, 1);
  static const fast = Duration(milliseconds: 90);
  static const base = Duration(milliseconds: 150);
  static const slow = Duration(milliseconds: 220);

  /// [d], or zero when Windows' "Animation effects" is off.
  static Duration of(BuildContext context, Duration d) =>
      MediaQuery.maybeDisableAnimationsOf(context) ?? false ? Duration.zero : d;
}
