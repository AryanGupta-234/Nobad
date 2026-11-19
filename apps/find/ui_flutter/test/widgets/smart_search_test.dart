// 0.8.5 smart search in the main window and the quick find bar: suggestions (history, phrases, names), the inline
// completion, the understood parts as removable chips, and the best guess. FakeEngine stands in for the engine.
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/features/search/smart_search.dart';
import 'package:nobad_find/platform/window.dart';
import 'package:nobad_find/state/suggest_controller.dart';

import '../support/fake_engine.dart';

final recentRows = find.descendant(of: find.byType(SuggestionRow), matching: find.text('Recent'));

String boxText(WidgetTester tester) => tester.widget<TextField>(find.byType(TextField).first).controller!.text;

Future<void> settle(WidgetTester tester) async {
  await tester.pump(const Duration(milliseconds: 60));
  await tester.pump(const Duration(milliseconds: 300));
}

Future<void> key(WidgetTester tester, LogicalKeyboardKey k) async {
  await tester.sendKeyEvent(k);
  await settle(tester);
}

void main() {
  group('main window', () {
    testWidgets('the list floats under the box; Tab takes the inline completion', (tester) async {
      final engine = FakeEngine(suggestions: true);
      await pumpApp(tester, engine);
      await type(tester, 'tax in d');
      await settle(tester);
      expect(find.text('in downloads'), findsOneWidget);
      expect(find.text('in documents'), findsOneWidget);
      expect(engine.suggested.last, 'tax in d');
      await key(tester, LogicalKeyboardKey.tab);
      expect(boxText(tester), 'tax in downloads');
    });

    testWidgets('→ at the end takes the completion too; in the middle it only moves the caret', (tester) async {
      final engine = FakeEngine(suggestions: true);
      await pumpApp(tester, engine);
      await type(tester, 'photos last w');
      await settle(tester);
      await key(tester, LogicalKeyboardKey.arrowRight);
      expect(boxText(tester), 'photos last week');
    });

    testWidgets('↑ from the first result goes up into the list; Enter takes it and keeps it', (tester) async {
      final engine = FakeEngine(suggestions: true);
      await pumpApp(tester, engine);
      await type(tester, 'tax');
      await settle(tester);
      expect(find.text('old tax scan.pdf'), findsNWidgets(2)); // a suggestion and a result
      await key(tester, LogicalKeyboardKey.arrowUp); // the list's last row
      await key(tester, LogicalKeyboardKey.enter);
      expect(boxText(tester), 'old tax scan.pdf');
      expect(engine.opened, isEmpty); // Enter took the suggestion, it didn't open a file
      expect(engine.history, ['old tax scan.pdf']);
    });

    testWidgets('↓ still moves the results, as before', (tester) async {
      final engine = FakeEngine(suggestions: true);
      await pumpApp(tester, engine);
      await type(tester, 'tax');
      await settle(tester);
      await key(tester, LogicalKeyboardKey.arrowDown);
      await key(tester, LogicalKeyboardKey.enter);
      expect(engine.opened, [2]);
      expect(engine.history, ['tax']); // a result used: the question is kept
    });

    testWidgets('history rows are marked and the x forgets one', (tester) async {
      final engine = FakeEngine(suggestions: true)..history.addAll(['tax pdf', 'taxes 2024']);
      await pumpApp(tester, engine);
      await type(tester, 'ta');
      await settle(tester);
      expect(recentRows, findsNWidgets(2));
      await tester.tap(find.bySemanticsLabel('Remove “tax pdf” from search history'));
      await settle(tester);
      expect(engine.history, ['taxes 2024']);
      expect(recentRows, findsOneWidget);
    });

    testWidgets('Esc closes the list before it clears the box', (tester) async {
      final engine = FakeEngine(suggestions: true);
      await pumpApp(tester, engine);
      await type(tester, 'tax in d');
      await settle(tester);
      await key(tester, LogicalKeyboardKey.escape);
      expect(find.text('in downloads'), findsNothing);
      expect(boxText(tester), 'tax in d');
      await key(tester, LogicalKeyboardKey.escape);
      expect(boxText(tester), '');
    });

    testWidgets('history off: no history rows', (tester) async {
      final engine = FakeEngine(suggestions: true, settings: {'welcome_seen': true, 'search_history': false})
        ..history.add('tax pdf');
      await pumpApp(tester, engine);
      await type(tester, 'ta');
      await settle(tester);
      expect(recentRows, findsNothing);
    });

    testWidgets('the best guess is marked, first, and Enter opens it', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine);
      await type(tester, 'notes');
      await settle(tester);
      expect(find.text('Best guess'), findsOneWidget);
      expect(find.text('The only match'), findsOneWidget);
      await key(tester, LogicalKeyboardKey.enter);
      expect(engine.opened, [2]);
    });

    testWidgets('no guess when the engine is unsure', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine);
      await type(tester, 'tax');
      await settle(tester);
      expect(find.text('Best guess'), findsNothing);
    });

    testWidgets('what the question was understood as: chips; the x searches without that part', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine);
      await type(tester, 'tax pdf in downloads');
      await settle(tester);
      expect(find.text('Downloads'), findsWidgets);
      expect(find.text('PDFs'), findsOneWidget);
      expect(find.text('“tax”'), findsOneWidget);
      await tester.tap(find.bySemanticsLabel('Remove Downloads'));
      await settle(tester);
      expect(boxText(tester), 'tax pdf');
    });

    testWidgets('Settings > Privacy: remember searches, and Clear history', (tester) async {
      final engine = FakeEngine()..history.add('rent pdf');
      await pumpApp(tester, engine, size: const Size(1080, 1200));
      await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
      await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
      await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Privacy & data'));
      await tester.pumpAndSettle();
      expect(find.text('Remember my searches'), findsOneWidget);
      await tester.tap(find.text('Clear history'));
      await tester.pumpAndSettle();
      expect(engine.calls, contains('history_clear'));
      expect(engine.history, isEmpty);
      expect(find.text('Search history cleared.'), findsOneWidget);
    });
  });

  group('quick find bar', () {
    Future<FakeWindow> pumpBar(WidgetTester tester, FakeEngine engine) async {
      tester.view.physicalSize = Size(BarSize.width.toDouble(), BarSize.height(8).toDouble());
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final w = FakeWindow();
      await tester.pumpWidget(NobadFindApp(engine: engine, mode: AppMode.bar, window: w));
      await tester.pump();
      return w;
    }

    Future<void> typeBar(WidgetTester tester, String text) async {
      await tester.enterText(find.byType(TextField), text);
      await tester.pump(const Duration(milliseconds: 120));
      await settle(tester);
    }

    testWidgets('suggestions above the results; ↑ reaches them, Enter takes one; the window fits both', (tester) async {
      final engine = FakeEngine(suggestions: true)..history.addAll(['taxes 2024', 'tax pdf']);
      final w = await pumpBar(tester, engine);
      await typeBar(tester, 'tax');
      expect(engine.suggested.last, 'tax');
      // the 2 kept questions (the 3 names starting with "tax" are the results already: not offered twice)
      expect(w.fits.last, 2 + 4);
      await key(tester, LogicalKeyboardKey.arrowUp);
      await key(tester, LogicalKeyboardKey.enter);
      expect(boxText(tester), 'tax pdf');
      expect(engine.opened, isEmpty);
      expect(engine.history.first, 'tax pdf');
    });

    testWidgets('Tab takes the inline completion; the best guess is marked; Enter opens it', (tester) async {
      final engine = FakeEngine(suggestions: true);
      await pumpBar(tester, engine);
      await typeBar(tester, 'tax no');
      await key(tester, LogicalKeyboardKey.tab);
      expect(boxText(tester), 'tax notes.txt');
      await settle(tester);
      expect(find.text('Best guess'), findsOneWidget);
      await key(tester, LogicalKeyboardKey.enter);
      expect(engine.opened, [2]);
    });

    testWidgets('Esc closes the suggestions first, then hides', (tester) async {
      final engine = FakeEngine(suggestions: true)..history.add('tax pdf');
      final w = await pumpBar(tester, engine);
      await typeBar(tester, 'tax');
      expect(w.fits.last, 1 + 4);
      await key(tester, LogicalKeyboardKey.escape);
      expect(w.calls, isNot(contains('hide')));
      expect(w.fits.last, 4);
      await key(tester, LogicalKeyboardKey.escape);
      expect(w.calls, contains('hide'));
    });
  });

  group('SuggestController', () {
    test('the ghost only completes exactly what was typed', () async {
      final engine = FakeEngine(suggestions: true);
      final c = SuggestController(engine, debounce: Duration.zero);
      c.typed('photos last w');
      await Future<void>.delayed(const Duration(milliseconds: 5));
      expect(c.ghostFor('photos last w'), 'eek');
      expect(c.ghostFor('photos last'), ''); // typed on since: not this one
      expect(c.ghostFor('PHOTOS LAST W'), '');
      c.dispose();
    });

    test('↑ comes into the list from the results, ↓ goes back out', () async {
      final engine = FakeEngine(suggestions: true);
      final c = SuggestController(engine, debounce: Duration.zero);
      c.typed('tax');
      await Future<void>.delayed(const Duration(milliseconds: 5));
      expect(c.items, hasLength(3));
      expect(c.down(), isFalse); // results below: ↓ is theirs
      expect(c.up(atTop: false), isFalse); // not on the first result: ↑ is theirs too
      expect(c.up(atTop: true), isTrue);
      expect(c.highlighted, 2);
      c.up(atTop: true);
      c.up(atTop: true);
      c.up(atTop: true);
      expect(c.highlighted, 0); // stays at the top
      c.down();
      c.down();
      c.down();
      expect(c.highlighted, -1); // back to the results
      expect(c.close(), isTrue);
      expect(c.isOpen, isFalse);
      expect(c.close(), isFalse);
      c.dispose();
    });

    test('an engine without suggest: nothing, and never an error', () async {
      final engine = FakeEngine()..offline = true;
      final c = SuggestController(engine, debounce: Duration.zero);
      c.typed('tax');
      await Future<void>.delayed(const Duration(milliseconds: 5));
      expect(c.items, isEmpty);
      expect(c.isOpen, isFalse);
      c.dispose();
    });

    test('models read the contract shapes and drop rows they cannot use', () {
      final s = Suggestions.fromJson({
        'items': [
          {'text': 'tax pdf', 'kind': 'history', 'label': 'tax pdf', 'detail': ''},
          {'text': '', 'kind': 'file', 'label': 'x', 'detail': ''},
          {'text': 'a', 'kind': 'evil', 'label': 'a', 'detail': ''},
          {'text': 'b.pdf', 'kind': 'file', 'label': 'b.pdf', 'detail': r'C:\x', 'id': 3},
        ],
        'complete': 'tax pdf',
      });
      expect(s.items.map((i) => i.text), ['tax pdf', 'b.pdf']);
      expect(s.items.last.id, 3);
      final a = SearchAnswer.fromJson({
        'results': [
          {'id': 3, 'name': 'b.pdf'},
        ],
        'parts': [
          {'kind': 'folder', 'label': 'Downloads', 'without': 'b'},
          {'kind': 'kind', 'label': ''},
          'junk',
        ],
        'best': {'id': 3, 'reason': 'Exact name'},
      });
      expect(a.parts.single.label, 'Downloads');
      expect(a.hasGuess, isTrue);
      expect(
        SearchAnswer.fromJson({
          'results': [],
          'best': {'id': 9, 'reason': ''},
        }).hasGuess,
        isFalse,
      );
    });
  });
}
