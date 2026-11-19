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

  /// Reading width of a page column (about 75 characters of body text at 14 px, plus panels).
  static const column = 880.0;

  /// The widest the content gets (centred beyond it, so 4K stays composed).
  static const maxContent = 1600.0;

  /// From here the search shows the detail pane, Index becomes a two-column dashboard, Settings two panes.
  static const wide = 1100.0;
}

abstract final class NbRadius {
  static const key = Radius.circular(6);
  static const control = Radius.circular(12);
  static const row = Radius.circular(16);
  static const panel = Radius.circular(24);
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
  static const fast = Duration(milliseconds: 120);
  static const base = Duration(milliseconds: 200);
  static const slow = Duration(milliseconds: 320);

  /// [d], or zero when Windows' "Animation effects" is off.
  static Duration of(BuildContext context, Duration d) =>
      MediaQuery.maybeDisableAnimationsOf(context) ?? false ? Duration.zero : d;
}
