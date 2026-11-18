/// NOBAD tokens, the same values as nobadfind/ui/app.css (one NOBAD orange, black, soft whites).
library;

import 'package:flutter/widgets.dart';

abstract final class Nb {
  static const orange = Color(0xFFFF4D00);
  static const bg = Color(0xFF07080A);
  static const bg2 = Color(0xFF0C0E11);
  static const bg3 = Color(0xFF12151A);
  static const text = Color(0xFFF3F4F6);
  static const muted = Color(0xADE8ECF1); // rgba(232, 236, 241, .68)
  static const dim = Color(0x73E8ECF1); // .45
  static const line = Color(0x14FFFFFF); // .08
  static const line2 = Color(0x26FFFFFF); // .15
  static const warn = Color(0xFFFFB38A);

  static Color orangeA(double a) => orange.withValues(alpha: a);
}
