import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/platform/window.dart';

import '../support/fake_engine.dart';

// Dark screenshots with the test font (glyphs are boxes; layout, colours and spacing are what's compared).
// Update with: flutter test --update-goldens test/golden
void main() {
  testWidgets('search screen, dark', (tester) async {
    tester.view.physicalSize = const Size(1080, 720);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final engine = FakeEngine();
    await tester.pumpWidget(NobadFindApp(engine: engine, window: FakeWindow()));
    engine.emit(const StatusEvent(EngineStatus(level: 'gentle', reason: "Gentle: you're using the PC",
        phase: 'watching', files: 48210)));
    await tester.enterText(find.byType(TextField), 'tax');
    await tester.pump(const Duration(milliseconds: 80));
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    await tester.pumpAndSettle();
    await expectLater(find.byType(NobadFindApp), matchesGoldenFile('search_dark.png'));
  });

  testWidgets('quick find bar, dark', (tester) async {
    tester.view.physicalSize = Size(BarSize.width.toDouble(), BarSize.height(4).toDouble());
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final engine = FakeEngine();
    await tester.pumpWidget(NobadFindApp(engine: engine, mode: AppMode.bar, window: FakeWindow()));
    await tester.enterText(find.byType(TextField), 'tax');
    await tester.pump(const Duration(milliseconds: 120));
    await tester.pumpAndSettle();
    await expectLater(find.byType(NobadFindApp), matchesGoldenFile('bar_dark.png'));
  });
}
