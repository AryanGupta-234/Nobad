import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/engine_api.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/features/search/result_tile.dart';

import '../support/fake_engine.dart';

void main() {
  testWidgets('home first, then results as you type', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    expect(find.text('Recently changed'), findsOneWidget);
    expect(find.text('Recently changed'), findsOneWidget);
    expect(find.text('tax notes.txt'), findsOneWidget); // recently changed, newest first

    await type(tester, 'tax');
    expect(engine.searches.last, 'tax');
    expect(find.text('tax return 2025.pdf'), findsOneWidget);
    expect(find.textContaining('results · 4 ms'), findsOneWidget);
    expect(find.text('Less sure'), findsOneWidget); // the weak result comes after the divider
    expect(find.text('Recently changed'), findsNothing);
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

  testWidgets('Ctrl+C copies the path; Shift+Delete asks, then forgets', (tester) async {
    final engine = FakeEngine();
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String;
      return null;
    });
    await pumpApp(tester, engine);
    await type(tester, 'notes');
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.keyC);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump();
    expect(copied, r'C:\Users\me\Desktop\tax notes.txt');
    expect(find.text('Path copied.'), findsOneWidget);

    await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.delete);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
    await tester.pumpAndSettle();
    expect(find.text('Forget "tax notes.txt" and keep it out of the index from now on?'), findsOneWidget);
    await tester.tap(find.text('Forget'));
    await tester.pumpAndSettle();
    expect(engine.forgotten, [2]);
    expect(find.text('Forgotten. Undo it in Settings → Never search.'), findsOneWidget);
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

  testWidgets('hide after opening, when that setting is on', (tester) async {
    final engine = FakeEngine(settings: const {'welcome_seen': true, 'bg_notice_seen': true, 'hide_after_open': true});
    final w = await pumpApp(tester, engine);
    await type(tester, 'notes');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(w.calls, contains('hide'));
  });

  testWidgets('Esc clears the box, a second Esc hides the window', (tester) async {
    final engine = FakeEngine();
    final w = await pumpApp(tester, engine);
    await type(tester, 'tax');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('Recently changed'), findsOneWidget);
    expect(w.calls, isNot(contains('hide')));
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pump();
    expect(w.calls, contains('hide'));
    expect(engine.calls, contains('ui_hidden'));
  });

  testWidgets('a category tile, then a narrower tile, set the filters; the filter bar clears them', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await tester.tap(find.text('Documents').last); // Home's tile (the sidebar has one too)
    await tester.pumpAndSettle();
    expect(engine.searchFilters.last.kind, 'document');
    expect(find.text('DOCUMENTS'), findsOneWidget); // the page header names the category
    await tester.tap(find.text('PDFs'));
    await tester.pumpAndSettle();
    expect(engine.searchFilters.last.kind, 'pdf');
    expect(find.text('tax return 2025.pdf'), findsOneWidget);
    expect(find.text('Clear filters'), findsOneWidget);
    await tester.tap(find.text('Clear filters'));
    await tester.pumpAndSettle();
    expect(find.text('Recently changed'), findsOneWidget);
  });

  testWidgets('a kind from the filter menu, and Any folder asks the engine for a folder', (tester) async {
    final engine = FakeEngine()..pickAnswer = r'C:\Users\me\Documents';
    await pumpApp(tester, engine);
    await type(tester, 'tax');
    await tester.tap(find.text('Any kind'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('PDFs').last);
    await tester.pumpAndSettle();
    expect(engine.searchFilters.last.kind, 'pdf');
    await tester.tap(find.text('Any folder'));
    await tester.pumpAndSettle();
    expect(engine.calls, contains('pick_folder'));
    expect(engine.searchFilters.last.folder, r'C:\Users\me\Documents');
    expect(find.text('In Documents'), findsOneWidget);
  });

  testWidgets('a folder window that is already open is not a cancel: say so', (tester) async {
    final engine = FakeEngine()..pickBusy = true;
    await pumpApp(tester, engine);
    await tester.tap(find.text('Any folder'));
    await tester.pump();
    expect(find.text('The folder window is already open.'), findsOneWidget);
    expect(engine.searchFilters.where((f) => f.folder.isNotEmpty), isEmpty);
  });

  testWidgets('the main hotkey tells the engine the window is on screen', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    engine.emit(const ShowEvent('main'));
    await tester.pump();
    expect(engine.calls, contains('ui_shown'));
  });

  testWidgets('"Here" appears when the engine says where the hotkey was pressed', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    engine.emit(const HereEvent(r'C:\Users\me\Downloads'));
    await tester.pump();
    expect(find.text('Here: Downloads'), findsOneWidget);
  });

  testWidgets('status line follows the engine events', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    engine.emit(
      const StatusEvent(
        EngineStatus(level: 'gentle', reason: "Gentle: you're using the PC", phase: 'text', files: 12345),
      ),
    );
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
    expect(find.textContaining("engine isn't running"), findsWidgets);
  });

  testWidgets('previews are asked for only for photos, videos and PDFs on screen', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    engine.thumbsAsked.clear();
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

  testWidgets('the main hotkey brings the window up; the bar hands its words over', (tester) async {
    final engine = FakeEngine();
    final window = await pumpApp(tester, engine);
    engine.emit(const ShowEvent('main'));
    engine.emit(const ShowEvent('bar')); // not this window's
    await tester.pump();
    expect(window.calls, ['front']);
    engine.emit(const ShowEvent('main', text: 'tax pdf'));
    await tester.pump(const Duration(milliseconds: 120));
    await tester.pump();
    expect(engine.searches.last, 'tax pdf');
  });

  testWidgets('quitting closes the window', (tester) async {
    final engine = FakeEngine();
    final window = await pumpApp(tester, engine);
    engine.emit(const QuittingEvent());
    await tester.pump();
    expect(window.calls, contains('close'));
  });
}
