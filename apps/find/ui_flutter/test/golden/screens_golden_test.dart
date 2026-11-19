// Screenshots of every main screen, dark and light, drawn with the real Windows fonts (test/support loads them
// from C:\Windows\Fonts; on a PC without them the test font's boxes are drawn instead and the goldens differ).
// Update with: flutter test --update-goldens test/golden
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/app/scope.dart' show SettingsPage;
import 'package:nobad_find/features/consent/download_consent_dialog.dart';
import 'package:nobad_find/platform/demo.dart';
import 'package:nobad_find/platform/window.dart';

import '../support/fake_engine.dart';

FakeEngine engineFor(String theme, {bool welcome = false}) => FakeEngine(
    files: demoFiles(),
    settings: {'theme': theme, 'welcome_seen': !welcome, 'bg_notice_seen': false});

Future<void> shoot(WidgetTester tester, String name) async {
  await tester.pumpAndSettle();
  await tester.runAsync(() async {
    for (final e in find.byType(Image).evaluate()) {
      await precacheImage((e.widget as Image).image, e);
    }
  });
  await tester.pumpAndSettle();
  await expectLater(find.byKey(shotBoundary), matchesGoldenFile('$name.png'));
}

void main() {
  setUpAll(loadWindowsFonts);

  for (final theme in ['dark', 'light']) {
    group(theme, () {
      testWidgets('home', (tester) async {
        await pumpApp(tester, engineFor(theme));
        await shoot(tester, 'home_$theme');
      });

      testWidgets('results', (tester) async {
        await pumpApp(tester, engineFor(theme));
        await type(tester, 'tax');
        await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
        await shoot(tester, 'results_$theme');
      });

      testWidgets('index', (tester) async {
        await pumpApp(tester, engineFor(theme), size: const Size(1080, 1500));
        await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
        await tester.sendKeyEvent(LogicalKeyboardKey.digit2);
        await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
        await shoot(tester, 'index_$theme');
      });

      for (final page in [SettingsPage.general, SettingsPage.models, SettingsPage.performance, SettingsPage.privacy,
          SettingsPage.about]) {
        testWidgets('settings ${page.name}', (tester) async {
          await pumpApp(tester, engineFor(theme), size: const Size(1080, 900));
          await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
          await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
          await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
          await tester.pumpAndSettle();
          await tester.tap(find.text(page.label).last);
          await shoot(tester, 'settings_${page.name}_$theme');
        });
      }

      testWidgets('welcome', (tester) async {
        await pumpApp(tester, engineFor(theme, welcome: true));
        await shoot(tester, 'welcome_$theme');
      });

      testWidgets('consent dialog', (tester) async {
        await pumpApp(tester, engineFor(theme));
        askDownloadConsent(appNavigator.currentContext!, 'photo');
        await shoot(tester, 'consent_$theme');
      });

      testWidgets('quick find bar', (tester) async {
        tester.view.physicalSize = Size(BarSize.width.toDouble(), BarSize.height(5).toDouble());
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        await tester.pumpWidget(NobadFindApp(engine: engineFor(theme), mode: AppMode.bar, window: FakeWindow()));
        await tester.enterText(find.byType(TextField), 'tax');
        await tester.pump(const Duration(milliseconds: 150));
        await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
        await shoot(tester, 'bar_$theme');
      });
    });
  }
}
