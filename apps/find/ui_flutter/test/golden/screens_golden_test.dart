// Screenshots of every main screen, dark and light, drawn with the real Windows fonts (test/support loads them
// from C:\Windows\Fonts; on a PC without them the test font's boxes are drawn instead and the goldens differ).
// Update with: flutter test --update-goldens test/golden
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/features/consent/download_consent_dialog.dart';
import 'package:nobad_find/platform/demo.dart';
import 'package:nobad_find/platform/window.dart';

import '../support/fake_engine.dart';

FakeEngine engineFor(String theme, {bool welcome = false}) =>
    FakeEngine(files: demoFiles(), settings: {'theme': theme, 'welcome_seen': !welcome, 'bg_notice_seen': false});

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

  const sizes = {'1280': Size(1280, 800), '2560': Size(2560, 1440)};
  for (final theme in ['dark', 'light']) {
    group(theme, () {
      for (final MapEntry(key: w, value: size) in sizes.entries) {
        testWidgets('home $w', (tester) async {
          await pumpApp(tester, engineFor(theme), size: size);
          await shoot(tester, 'home_${w}_$theme');
        });

        testWidgets('results $w', (tester) async {
          await pumpApp(tester, engineFor(theme), size: size);
          await type(tester, 'tax');
          await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
          await shoot(tester, 'results_${w}_$theme');
        });

        testWidgets('results as cards $w', (tester) async {
          await pumpApp(tester, engineFor(theme), size: size);
          await type(tester, 'a');
          await tester.tap(find.text('Cards'));
          await shoot(tester, 'cards_${w}_$theme');
        });

        testWidgets('index $w', (tester) async {
          await pumpApp(tester, engineFor(theme), size: size);
          await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
          await tester.sendKeyEvent(LogicalKeyboardKey.digit2);
          await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
          await shoot(tester, 'index_${w}_$theme');
        });

        testWidgets('settings $w', (tester) async {
          await pumpApp(tester, engineFor(theme), size: size);
          await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
          await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
          await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
          await tester.pumpAndSettle();
          await tester.tap(find.text('Models').last);
          await shoot(tester, 'settings_${w}_$theme');
        });
      }

      for (final size in const [Size(800, 600), Size(1280, 800)]) {
        testWidgets('actions on the selected row ${size.width.toInt()}', (tester) async {
          await pumpApp(tester, engineFor(theme), size: size);
          await type(tester, 'tax');
          await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
          await shoot(tester, 'actions_${size.width.toInt()}_$theme');
        });
      }

      testWidgets('welcome', (tester) async {
        await pumpApp(tester, engineFor(theme, welcome: true), size: const Size(1280, 800));
        await shoot(tester, 'welcome_$theme');
      });

      testWidgets('consent dialog', (tester) async {
        await pumpApp(tester, engineFor(theme), size: const Size(1280, 800));
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
