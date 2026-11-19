import 'dart:ui';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart' show EditableText, Opacity, RichText, Text;
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/app/scope.dart';
import 'package:nobad_find/engine/engine_api.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/platform/window.dart';

import '../support/fake_engine.dart';

Future<void> ctrl(WidgetTester tester, LogicalKeyboardKey k) async {
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(k);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets("the engine's tray menu opens a page: show settings / show index", (tester) async {
    final engine = FakeEngine();
    final w = await pumpApp(tester, engine);
    engine.emit(const ShowEvent('settings'));
    await tester.pumpAndSettle();
    expect(find.text('General'), findsWidgets);
    expect(w.calls, contains('front'));
    engine.emit(const ShowEvent('index'));
    await tester.pumpAndSettle();
    expect(find.text('INDEX'), findsOneWidget);
  });

  testWidgets('--page settings starts on Settings', (tester) async {
    tester.view.physicalSize = const Size(1080, 720);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(NobadFindApp(engine: FakeEngine(), window: FakeWindow(), splash: false,
        startPage: AppPage.parse(['--page', 'settings'])));
    await tester.pumpAndSettle();
    expect(find.text('SETTINGS'), findsOneWidget);
  });

  testWidgets('no engine: Index shows no numbers and no actions, Settings says so and is read-only', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine, size: const Size(1080, 1200));
    await ctrl(tester, LogicalKeyboardKey.digit2);
    expect(find.text('Reading documents'), findsOneWidget);
    engine.linkState = Link.offline;
    await tester.pumpAndSettle();
    expect(find.text('Reading documents'), findsNothing);
    expect(find.text('Pause for 1 hour'), findsNothing);
    expect(find.text("The engine isn't running. Trying again…"), findsWidgets);
    await ctrl(tester, LogicalKeyboardKey.digit3);
    expect(find.textContaining("NOBAD Find's engine isn't running"), findsOneWidget);
    final before = engine.settingsSet.length;
    await tester.tap(find.text('Start with Windows'), warnIfMissed: false);
    await tester.pump();
    expect(engine.settingsSet.length, before);
  });

  testWidgets('Esc clears the words, then the filters, then hides', (tester) async {
    final engine = FakeEngine();
    final w = await pumpApp(tester, engine);
    await tester.tap(find.text('PDFs'));
    await tester.pumpAndSettle();
    await type(tester, 'tax');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.text('Clear filters'), findsOneWidget); // the words went, the filter stays
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.text('Clear filters'), findsNothing);
    expect(w.calls, isNot(contains('hide')));
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(w.calls, contains('hide'));
  });

  testWidgets("the bar's words reach the box even when Index is open", (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await ctrl(tester, LogicalKeyboardKey.digit2);
    engine.emit(const ShowEvent('main', text: 'tax notes'));
    await tester.pumpAndSettle();
    expect(engine.searches.last, 'tax notes');
    expect(find.text('tax notes.txt'), findsOneWidget);
  });

  testWidgets('hiding after an open, or minimizing, tells the engine; restoring too', (tester) async {
    final engine = FakeEngine(settings: const {'welcome_seen': true, 'bg_notice_seen': true, 'hide_after_open': true});
    await pumpApp(tester, engine);
    await type(tester, 'notes');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(engine.calls.where((c) => c == 'ui_hidden'), hasLength(1));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(engine.calls.last, 'ui_shown');
  });

  testWidgets('Recently changed loads when the engine comes, and again after a failure', (tester) async {
    final engine = FakeEngine(link: Link.offline)..offline = true;
    await pumpApp(tester, engine);
    expect(find.text('tax notes.txt'), findsNothing);
    engine.offline = false;
    engine.linkState = Link.connected;
    await tester.pumpAndSettle();
    expect(find.text('tax notes.txt'), findsOneWidget);
  });

  testWidgets('Forget asks with Cancel focused: Enter keeps the file', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await type(tester, 'notes');
    await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.delete);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
    await tester.pumpAndSettle();
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(engine.forgotten, isEmpty);
  });

  testWidgets('with animations off, results are fully there in the first frame', (tester) async {
    tester.view.physicalSize = const Size(1080, 720);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final engine = FakeEngine();
    await tester.pumpWidget(NobadFindApp(engine: engine, window: FakeWindow(), splash: false, reduceMotion: true));
    await tester.pump();
    await tester.enterText(find.byType(EditableText).first, 'return');
    await tester.pump(const Duration(milliseconds: 80));
    await tester.pump();
    expect(find.text('tax return 2025.pdf'), findsOneWidget);
    final faded = tester.widgetList<Opacity>(find.byType(Opacity)).where((o) => o.opacity > 0 && o.opacity < 1);
    expect(faded, isEmpty);
  });

  testWidgets('a busy phase with no known end does not animate forever', (tester) async {
    final engine = FakeEngine();
    await pumpApp(tester, engine);
    await ctrl(tester, LogicalKeyboardKey.digit2);
    final full = await engine.statusFull();
    engine.emit(
      StatusFullEvent(
        EngineStatus(
          level: 'gentle',
          reason: 'r',
          phase: 'watching',
          files: 1,
          details: IndexDetailsWith.busyWatching(full.details!),
        ),
      ),
    );
    await tester.pumpAndSettle(); // would time out with an endless animation
    expect(find.text('Watching for changes'), findsOneWidget);
  });

  testWidgets('a file name with markup or control characters is shown exactly as it is', (tester) async {
    const name = '<b>x</b> &amp; \u202Eevil\u0007 [link](http://a).txt';
    final engine = FakeEngine(
      files: [const FileResult(id: 9, name: name, dir: r'C:\x', kind: 'text')],
    );
    await pumpApp(tester, engine);
    await type(tester, 'evil');
    final shown = tester.widgetList<RichText>(find.byType(RichText)).map((r) => r.text.toPlainText());
    expect(shown, contains(name));
    expect(find.byWidgetPredicate((w) => w is Text && w.data == name), findsOneWidget);
  });

  testWidgets('the quick find bar hides when it loses the focus', (tester) async {
    tester.view.physicalSize = Size(BarSize.width.toDouble(), BarSize.height(8).toDouble());
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final w = FakeWindow();
    final engine = FakeEngine();
    await tester.pumpWidget(NobadFindApp(engine: engine, mode: AppMode.bar, window: w));
    engine.emit(const ShowEvent('bar'));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump(const Duration(milliseconds: 600));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump(const Duration(milliseconds: 300));
    expect(w.calls, contains('hide'));
  });
}

/// The fake's details with "Watching for changes" running and no total.
extension IndexDetailsWith on IndexDetails {
  static IndexDetails busyWatching(IndexDetails d) => IndexDetails(
    phases: [
      for (final p in d.phases) p.id == 'watching' ? PhaseRow(id: p.id, label: p.label, state: PhaseState.running) : p,
    ],
    history: d.history,
    resources: d.resources,
    models: d.models,
    activity: d.activity,
  );
}
