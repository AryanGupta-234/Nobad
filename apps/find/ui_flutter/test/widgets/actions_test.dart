import 'package:flutter/gestures.dart' show kSecondaryButton;
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart' show Text;
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter/foundation.dart';
import 'package:nobad_find/features/search/result_tile.dart';
import 'package:nobad_find/widgets/pressable.dart';

import '../support/fake_engine.dart';

Finder action(String label) => find.byWidgetPredicate((w) => w is Pressable && w.semanticLabel == label);

void main() {
  String? copied;
  setUp(() => copied = null);
  void watchClipboard(WidgetTester tester) {
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String;
      return null;
    });
  }

  testWidgets('at 800 px the selected row shows its actions; they work', (tester) async {
    final engine = FakeEngine();
    watchClipboard(tester);
    await pumpApp(tester, engine, size: const Size(800, 600));
    await type(tester, 'notes');
    await tester.pumpAndSettle();
    expect(action('Open with…'), findsOneWidget);
    await tester.tap(action('Copy path'));
    await tester.pumpAndSettle();
    expect(copied, r'C:\Users\me\Desktop\tax notes.txt');
    await tester.tap(action('Open with…'));
    await tester.pumpAndSettle();
    expect(engine.openedWith, [2]);
  });

  testWidgets('right-click opens the menu with every action and its shortcut', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.windows;
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    final engine = FakeEngine();
    watchClipboard(tester);
    await pumpApp(tester, engine, size: const Size(800, 600));
    await type(tester, 'tax');
    await tester.tap(find.text('tax notes.txt'), buttons: kSecondaryButton);
    await tester.pumpAndSettle();
    for (final label in ['Open', 'Open with…', 'Show in folder', 'Copy path', 'Copy name', 'Details', 'Forget…']) {
      expect(find.text(label), findsWidgets, reason: label);
    }
    expect(find.text('Ctrl+Shift+↵'), findsOneWidget); // the shortcuts are shown
    await tester.tap(find.text('Copy name').last);
    await tester.pumpAndSettle();
    expect(copied, 'tax notes.txt');
    debugDefaultTargetPlatformOverride = null;
  });

  testWidgets('below 1100 px, Space after the arrows opens the details as a sheet; Esc closes it', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(900, 700));
    await type(tester, 'tax');
    expect(find.byType(DetailPane), findsNothing); // no detail pane at this width
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    await tester.sendKeyEvent(LogicalKeyboardKey.space);
    await tester.pumpAndSettle();
    expect(find.byType(DetailPane), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.text('tax notes.txt'), findsWidgets); // still searching: Esc closed the sheet only
    expect(engine.searches.last, 'tax');
  });

  testWidgets('Ctrl+Shift+Enter is Open with; Page Down, Home and End move the selection', (tester) async {
    final engine = FakeEngine(files: manyFiles(30));
    await pumpApp(tester, engine);
    await type(tester, 'report');
    await tester.sendKeyEvent(LogicalKeyboardKey.pageDown);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump();
    expect(engine.openedWith, [108]);
    await tester.sendKeyEvent(LogicalKeyboardKey.end);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(engine.opened.last, 129);
    await tester.sendKeyEvent(LogicalKeyboardKey.home);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(engine.opened.last, 100);
  });

  testWidgets('an older engine: Open with says it needs a newer one', (tester) async {
    final engine = FakeEngine()..old = true;
    await pumpApp(tester, engine, size: const Size(800, 600));
    await type(tester, 'notes');
    await tester.pumpAndSettle();
    await tester.tap(action('Open with…'));
    await tester.pump();
    expect(find.textContaining("can't do that yet"), findsOneWidget);
  });
}
