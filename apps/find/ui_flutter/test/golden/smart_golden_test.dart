// 0.8.5 smart search, dark and light: the suggestions under the box (history, a name), the understood parts as
// chips with the best guess on top, and the quick find bar with its suggestions and the guess marked.
// Update with: flutter test --update-goldens test/golden
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/platform/demo.dart';
import 'package:nobad_find/platform/window.dart';

import '../support/fake_engine.dart';

FakeEngine smartEngine(String theme) => FakeEngine(
  files: demoFiles(),
  suggestions: true,
  settings: {'theme': theme, 'welcome_seen': true, 'bg_notice_seen': true},
)..history.addAll(['invoice pdf in downloads', 'invoices from last month', 'rent agreement']);

Future<void> shoot(WidgetTester tester, String name) async {
  await tester.pumpAndSettle();
  await expectLater(find.byKey(shotBoundary), matchesGoldenFile('$name.png'));
}

void main() {
  setUpAll(loadWindowsFonts);

  for (final theme in ['dark', 'light']) {
    group(theme, () {
      testWidgets('suggestions while typing', (tester) async {
        await pumpApp(tester, smartEngine(theme), size: const Size(1180, 760));
        await type(tester, 'inv');
        await tester.pump(const Duration(milliseconds: 100));
        await shoot(tester, 'smart_suggest_1180_$theme');
      });

      testWidgets('parts and the best guess', (tester) async {
        await pumpApp(tester, smartEngine(theme), size: const Size(1180, 760));
        await type(tester, 'invoice pdf in downloads'); // nothing left to suggest: the results in full
        await shoot(tester, 'smart_guess_1180_$theme');
      });

      testWidgets('quick find bar with suggestions', (tester) async {
        tester.view.physicalSize = Size(BarSize.width.toDouble(), BarSize.height(4).toDouble());
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        await tester.pumpWidget(NobadFindApp(engine: smartEngine(theme), mode: AppMode.bar, window: FakeWindow()));
        await tester.enterText(find.byType(TextField), 'inv');
        await tester.pump(const Duration(milliseconds: 150));
        await shoot(tester, 'smart_bar_$theme');
      });
    });
  }
}
