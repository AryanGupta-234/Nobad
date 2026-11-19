import 'dart:async';
import 'dart:io';

import 'package:nobad_find/platform/window.dart';

/// Every test sees the same motion setting, whatever the PC's Windows "Animation effects" switch says (CI's
/// Windows Server has animations off). NOBAD_FIND_TEST_MOTION=off runs the suite as on a PC with them off.
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  debugAnimationsOff = Platform.environment['NOBAD_FIND_TEST_MOTION'] == 'off';
  await testMain();
}
