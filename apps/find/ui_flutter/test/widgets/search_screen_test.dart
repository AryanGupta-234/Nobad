import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/engine/rpc.dart';
import 'package:nobad_find/features/search/result_tile.dart';

import '../support/fake_engine.dart';

Future<void> pumpApp(WidgetTester tester, FakeEngine engine, {FakeWindow? window}) async {
  tester.view.physicalSize = const Size(1080, 720);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(NobadFindApp(engine: engine, window: window ?? FakeWindow()));
  await tester.pump();
}

Future<void> type(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  await tester.pump(const Duration(milliseconds: 80)); // debounce
  await tester.pump();
}

void main() {
  testWidgets('home first, then results as you type', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    expect(find.text('FIND ANYTHING ON THIS PC.'), findsOneWidget);

    await type(tester, 'tax');
    expect(engine.searches, ['tax']);
    expect(find.text('tax return 2025.pdf'), findsOneWidget);
    expect(find.text('tax notes.txt'), findsOneWidget);
    expect(find.textContaining('results · 4 ms'), findsOneWidget);
    expect(find.text('LESS SURE'), findsOneWidget); // the weak result comes after the divider
    expect(find.text('FIND ANYTHING ON THIS PC.'), findsNothing);
  });

  testWidgets('a file name is shown as plain text, never as markup', (tester) async {
    await pumpApp(tester, FakeEngine());
    await type(tester, 'quotes');
    expect(find.text('<b>tax</b> & "quotes".docx'), findsOneWidget);
  });

  testWidgets('arrows choose, Enter opens, Ctrl+Enter shows in folder', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await type(tester, 'tax');
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    await tester.pump();
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(engine.opened, [2]);

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowUp);
    await tester.pump();
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump();
    expect(engine.revealed, [1]);

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowUp); // wraps to the last one
    await tester.pump();
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(engine.opened.last, 5);
  });

  testWidgets('clicking a result opens it; a missing file says so', (tester) async {
    final engine = FakeEngine()..openOk = false;
    await pumpApp(tester, engine);
    await type(tester, 'notes');
    await tester.tap(find.text('tax notes.txt'));
    await tester.pump();
    expect(engine.opened, [2]);
    expect(find.text("That file isn't there any more."), findsOneWidget);
  });

  testWidgets('Esc clears the box', (tester) async {
    await pumpApp(tester, FakeEngine());
    await type(tester, 'tax');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pump(const Duration(milliseconds: 80));
    expect(find.text('FIND ANYTHING ON THIS PC.'), findsOneWidget);
  });

  testWidgets('status line follows the engine events', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    engine.emit(const StatusEvent(EngineStatus(level: 'gentle', reason: "Gentle: you're using the PC",
        phase: 'text', files: 12345)));
    await tester.pump();
    expect(find.text('12,345 files indexed · Working gently · Reading text'), findsOneWidget);
    expect(find.text("Gentle: you're using the PC"), findsOneWidget);

    engine.linkState = Link.offline;
    await tester.pump();
    expect(find.text("The engine isn't running. Trying again…"), findsOneWidget);
  });

  testWidgets('engine offline while searching', (tester) async {
    final engine = FakeEngine()..offline = true;
    await pumpApp(tester, engine);
    await type(tester, 'tax');
    expect(find.textContaining("engine isn't running"), findsOneWidget);
  });

  testWidgets('previews are asked for only for photos, videos and PDFs on screen', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await type(tester, 'a');
    expect(engine.thumbsAsked.toSet(), {1, 3, 5});
  });

  testWidgets('long lists are virtualized', (tester) async {
    final engine = FakeEngine(files: manyFiles(500));
    await pumpApp(tester, engine);
    await type(tester, 'report');
    expect(find.byType(ResultTile).evaluate().length, lessThan(40));
    for (var i = 0; i < 30; i++) {
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    }
    await tester.pumpAndSettle();
    expect(find.text('report 30.pdf'), findsOneWidget); // the selection is scrolled into view
  });

  testWidgets('the main hotkey brings the window up', (tester) async {
    final engine = FakeEngine();
    final window = FakeWindow();
    await pumpApp(tester, engine, window: window);
    engine.emit(const ShowEvent('main'));
    engine.emit(const ShowEvent('bar')); // not this window's
    await tester.pump();
    expect(window.calls, ['front']);
  });
}
