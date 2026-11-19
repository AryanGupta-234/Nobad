import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart' show TextField;
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

Future<void> ctrl(WidgetTester tester, LogicalKeyboardKey k) async {
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(k);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
}

void main() {
  group('Index', () {
    testWidgets('shows the level and its reason; Pause for 1 hour, then Resume', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1600));
      await ctrl(tester, LogicalKeyboardKey.digit2);
      expect(find.text('Working gently'), findsOneWidget);
      expect(find.text('Reading documents'), findsOneWidget);
      expect(find.text('31,877 / 40,112'), findsOneWidget);
      expect(find.textContaining('done in about 9 min'), findsOneWidget);
      expect(find.text('Text reader'), findsNWidgets(2));
      expect(find.textContaining('The index is encrypted on disk'), findsOneWidget);
      await tester.tap(find.text('Pause for 1 hour'));
      await tester.pumpAndSettle();
      expect(engine.calls, contains('pause_for'));
      expect(find.text('Paused'), findsWidgets);
      expect(find.text('Paused: you paused NOBAD Find for 60 min'), findsWidgets);
      await tester.tap(find.text('Resume'));
      await tester.pumpAndSettle();
      expect(find.text('Working gently'), findsOneWidget);
    });

    testWidgets('watches status_full only while open; there is no light theme to pick (0.8.5 is dark only)', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine);
      await ctrl(tester, LogicalKeyboardKey.digit2);
      expect(engine.watching, isTrue);
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.pumpAndSettle();
      expect(find.text('Light'), findsNothing);
      await ctrl(tester, LogicalKeyboardKey.digit1);
      expect(engine.watching, isFalse);
    });

    testWidgets('a model card downloads only after consent, then shows the progress', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1600));
      await ctrl(tester, LogicalKeyboardKey.digit2);
      await tester.tap(find.text('Download…').first);
      await tester.pumpAndSettle();
      expect(find.text('Download the meaning model?'), findsOneWidget);
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();
      expect(engine.calls, isNot(contains('download_meaning')));
      await tester.tap(find.text('Download…').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Download'));
      await tester.pumpAndSettle();
      expect(engine.calls, contains('download_meaning'));
      engine.emit(const DownloadEvent(id: 'meaning', state: 'downloading', gotMb: 11.5, sizeMb: 23, mbS: 4));
      await tester.pumpAndSettle();
      expect(find.text('Downloading 12 MB of 23 MB at 4.0 MB/s'), findsOneWidget);
    });
  });

  group('Settings', () {
    testWidgets('eight pages in the sidebar; a switch goes to the engine', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1000));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      for (final p in [
        'General',
        'Search',
        'What to index',
        'Models & languages',
        'Performance',
        'Privacy & data',
        'Shortcuts',
        'About',
      ]) {
        expect(find.text(p), findsWidgets);
      }
      await tester.tap(find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Start with Windows'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'autostart': true});
      await tester.tap(find.text('Performance'));
      await tester.pumpAndSettle();
      expect(find.text('Cyberpunk2077'), findsOneWidget);
      await tester.tap(find.text('Forget').first);
      await tester.pumpAndSettle();
      expect(find.text('Cyberpunk2077'), findsNothing);
      await tester.tap(find.text('About'));
      await tester.pumpAndSettle();
      expect(find.text('NOBAD. Software with a point of view.'), findsOneWidget);
    });

    testWidgets('a folder is added through the engine; Delete index needs DELETE typed', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1200));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.tap(find.text('What to index'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Custom'));
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {'scope': 'custom'});
      await tester.tap(find.text('Add folder').first);
      await tester.pumpAndSettle();
      expect(engine.settingsSet.last, {
        'roots': [r'C:\Users\me\Projects'],
      });
      expect(find.text(r'C:\Users\me\Projects'), findsOneWidget);

      await tester.tap(find.text('Privacy & data'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Delete index'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).last, 'delete');
      await tester.pump();
      await tester.tap(find.text('Delete index').last); // disabled: nothing happens
      await tester.pump();
      expect(engine.calls, isNot(contains('wipe')));
      await tester.enterText(find.byType(TextField).last, 'DELETE');
      await tester.pump();
      await tester.tap(find.text('Delete index').last);
      await tester.pumpAndSettle();
      expect(engine.calls, contains('wipe'));
      expect(find.text('Index deleted. Rebuilding.'), findsOneWidget);
    });

    testWidgets('Windows Search: one click, and the words say what happens', (tester) async {
      final engine = FakeEngine();
      await pumpApp(tester, engine, size: const Size(1080, 1000));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.tap(find.text('Privacy & data'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Windows Search indexing is on (delayed-auto, running)'), findsOneWidget);
      await tester.tap(find.text('Switch to NOBAD Find'));
      await tester.pumpAndSettle();
      expect(find.text('Done.'), findsOneWidget);
      expect(find.text('Go back to Windows Search'), findsOneWidget);
    });

    testWidgets('Quit asks the engine to quit', (tester) async {
      final engine = FakeEngine();
      final w = await pumpApp(tester, engine, size: const Size(1080, 1000));
      await ctrl(tester, LogicalKeyboardKey.digit3);
      await tester.tap(find.text('About'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Quit').last);
      await tester.pumpAndSettle();
      expect(engine.calls, contains('quit'));
      expect(w.calls, contains('close')); // the quitting event closes the window
    });
  });

  testWidgets('first run: the welcome, then Start searching remembers it', (tester) async {
    final engine = FakeEngine(settings: const {'welcome_seen': false, 'bg_notice_seen': true});
    await pumpApp(tester, engine);
    await tester.pumpAndSettle();
    expect(find.text('Start searching'), findsOneWidget);
    expect(find.text('Software with a point of view.'), findsOneWidget);
    await tester.ensureVisible(find.text('Start searching'));
    await tester.tap(find.text('Start searching'));
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'welcome_seen': true});
    expect(find.text('Start searching'), findsNothing);
  });

  testWidgets('the one-time notice on Index goes away with Got it', (tester) async {
    final engine = FakeEngine(settings: const {'welcome_seen': true, 'bg_notice_seen': false});
    await pumpApp(tester, engine);
    await ctrl(tester, LogicalKeyboardKey.digit2);
    expect(find.textContaining('Closing the window now stops indexing.'), findsOneWidget);
    await tester.tap(find.text('Got it'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Closing the window now stops indexing.'), findsNothing);
  });

  testWidgets('a notice from the engine shows as a toast', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    engine.emit(const NoticeEvent('The hotkey is used by another app. Pick another one in Settings.'));
    await tester.pump();
    expect(find.text('The hotkey is used by another app. Pick another one in Settings.'), findsOneWidget);
    await tester.pump(const Duration(seconds: 4));
  });
}
