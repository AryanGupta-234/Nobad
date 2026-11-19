import 'package:flutter/gestures.dart' show kSecondaryButton;
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/platform/window.dart';

import 'package:nobad_find/widgets/pressable.dart';

import '../support/fake_engine.dart';

Future<FakeWindow> pumpBar(WidgetTester tester, FakeEngine engine, {int rows = 8}) async {
  tester.view.physicalSize = Size(BarSize.width.toDouble(), BarSize.height(rows).toDouble());
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final w = FakeWindow();
  await tester.pumpWidget(NobadFindApp(engine: engine, mode: AppMode.bar, window: w));
  await tester.pump();
  return w;
}

Future<void> type(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  await tester.pump(const Duration(milliseconds: 120));
  await tester.pump();
}

void main() {
  test('bar geometry: a 52 px box, 38 px rows, placed like bar.py', () {
    expect(BarSize.height(0), 52);
    expect(BarSize.height(3), 52 + 1 + 3 * 38);
    expect(BarSize.height(20), BarSize.height(8));
    expect(BarSize.place(0, 0, 1920, 1040, 640, 64), (640, 314));
    expect(BarSize.place(-1920, 0, 0, 1080, 640, 64), (-1280, 328));
  });

  testWidgets('at most 8 rows tall; the rest scroll (0.8.5: no cut to 8 results)', (tester) async {
    final engine = FakeEngine(files: manyFiles(30));
    final w = await pumpBar(tester, engine);
    await type(tester, 'report');
    expect(find.textContaining('report '), findsWidgets);
    expect(find.textContaining('30 results', findRichText: true), findsOneWidget);
    expect(w.fits.last, 8);
    expect(find.text('Enter opens · Ctrl+Enter shows in folder · Alt+Enter full window · Esc hides'), findsOneWidget);

    await type(tester, '');
    expect(w.fits.last, 0);
  });

  testWidgets('no match is one row', (tester) async {
    final engine = FakeEngine();
    final w = await pumpBar(tester, engine, rows: 1);
    await type(tester, 'zebra');
    expect(find.text('zebra'), findsOneWidget); // inside "No match for zebra", as plain text
    expect(find.textContaining('No match for'), findsOneWidget);
    expect(w.fits.last, 1);
  });

  testWidgets('Enter opens and hides; Esc hides', (tester) async {
    final engine = FakeEngine();
    final w = await pumpBar(tester, engine);
    await type(tester, 'tax');
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump(const Duration(milliseconds: 200)); // the bar fades, then hides
    expect(engine.opened, [2]);
    expect(w.calls, ['hide']);

    await type(tester, 'tax');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pump(const Duration(milliseconds: 200));
    expect(w.calls, ['hide', 'hide']);
    expect(engine.opened, [2]);
  });

  testWidgets('Alt+Enter hands the words to the main window and hides', (tester) async {
    final engine = FakeEngine();
    final w = await pumpBar(tester, engine);
    await type(tester, 'tax pdf');
    await tester.sendKeyDownEvent(LogicalKeyboardKey.altLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.altLeft);
    await tester.pump(const Duration(milliseconds: 200));
    expect(engine.calls, contains('to_main'));
    expect(w.calls, ['hide']);
    expect(engine.opened, isEmpty);
  });

  testWidgets('a file that is gone keeps the bar up', (tester) async {
    final engine = FakeEngine()..openOk = false;
    final w = await pumpBar(tester, engine);
    await type(tester, 'tax');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(w.calls, isEmpty);
    expect(find.text("That file isn't there any more."), findsOneWidget);
  });

  testWidgets('the bar hotkey shows it, empty and focused', (tester) async {
    final engine = FakeEngine();
    final w = await pumpBar(tester, engine);
    await type(tester, 'tax');
    engine.emit(const ShowEvent('bar'));
    await tester.pump();
    expect(w.calls, ['showBar']);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '');
    engine.emit(const ShowEvent('main'));
    await tester.pump();
    expect(w.calls, ['showBar']);
  });

  testWidgets('long folders keep their end', (tester) async {
    final engine = FakeEngine(files: manyFiles(1));
    await pumpBar(tester, engine, rows: 1);
    await type(tester, 'report');
    final shown = find.textContaining('Archive');
    expect(shown, findsOneWidget);
    expect(tester.widget<Text>(shown).data, startsWith('…'));
  });

  testWidgets('right-click on a row: Open with and Copy path; the window grows for the menu', (tester) async {
    final engine = FakeEngine();
    final w = await pumpBar(tester, engine);
    await type(tester, 'tax');
    await tester.tap(find.text('tax notes.txt'), buttons: kSecondaryButton);
    await tester.pumpAndSettle();
    expect(w.fits.last, BarSize.maxRows);
    expect(find.text('Copy path'), findsOneWidget);
    await tester.tap(find.text('Open with…'));
    await tester.pumpAndSettle();
    expect(engine.openedWith, [2]);
  });

  testWidgets('the n mark opens the app menu: pause, quit', (tester) async {
    final engine = FakeEngine();
    await pumpBar(tester, engine);
    await tester.tap(find.byWidgetPredicate((w) => w is Pressable && w.semanticLabel == 'NOBAD Find menu'));
    await tester.pumpAndSettle();
    expect(find.text('Open NOBAD Find'), findsOneWidget);
    await tester.tap(find.text('Pause for 1 hour'));
    await tester.pumpAndSettle();
    expect(engine.calls, contains('pause_for'));
  });
}
