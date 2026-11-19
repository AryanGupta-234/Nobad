// How much UI work a keystroke costs with a big answer on screen (500 results), suggestions and the best guess on:
// the wall time of each frame's build, layout and paint in the test binding (no GPU raster here, so it is the UI
// thread's share only). Printed for docs/measurements.md; the assertion is loose so a busy PC doesn't fail it.
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_find/app/app.dart';
import 'package:nobad_find/platform/window.dart';

import '../support/fake_engine.dart';

double pct(List<double> v, double p) {
  final s = [...v]..sort();
  return s[((s.length - 1) * p).round()];
}

Future<List<double>> typeTimed(WidgetTester tester, Finder field, String text) async {
  final out = <double>[];
  for (var i = 1; i <= text.length; i++) {
    final sw = Stopwatch()..start();
    await tester.enterText(field, text.substring(0, i));
    await tester.pump(); // the keystroke's frame (box, ghost)
    await tester.pump(const Duration(milliseconds: 100)); // debounces run, the answer and suggestions arrive
    await tester.pump(const Duration(milliseconds: 16)); // the frame that shows them
    out.add(sw.elapsedMicroseconds / 1000);
  }
  return out;
}

void main() {
  testWidgets('main window: a keystroke with 500 results on screen', (tester) async {
    final engine = FakeEngine(files: manyFiles(500), suggestions: true)..history.addAll(['report pdf', 'reports 2024']);
    await pumpApp(tester, engine, size: const Size(1180, 760));
    await typeTimed(tester, find.byType(TextField).first, 'report'); // warm up
    await tester.enterText(find.byType(TextField).first, '');
    await tester.pump(const Duration(milliseconds: 400));
    final ms = await typeTimed(tester, find.byType(TextField).first, 'report 4');
    stdout.writeln(
      'PERF main 500 results: per keystroke (3 frames) p50 ${pct(ms, .5).toStringAsFixed(1)} ms, '
      'p90 ${pct(ms, .9).toStringAsFixed(1)} ms, max ${ms.reduce((a, b) => a > b ? a : b).toStringAsFixed(1)} ms',
    );
    expect(pct(ms, .5), lessThan(1000)); // debug-mode test timing on a shared PC: only catches a gross regression
  });

  testWidgets('quick find bar: a keystroke with 500 results in its list', (tester) async {
    tester.view.physicalSize = Size(BarSize.width.toDouble(), BarSize.height(8).toDouble());
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final engine = FakeEngine(files: manyFiles(500), suggestions: true)..history.add('report pdf');
    await tester.pumpWidget(NobadFindApp(engine: engine, mode: AppMode.bar, window: FakeWindow()));
    await tester.pump();
    await typeTimed(tester, find.byType(TextField), 'report');
    await tester.enterText(find.byType(TextField), '');
    await tester.pump(const Duration(milliseconds: 400));
    final ms = await typeTimed(tester, find.byType(TextField), 'report 4');
    stdout.writeln(
      'PERF bar 500 results: per keystroke (3 frames) p50 ${pct(ms, .5).toStringAsFixed(1)} ms, '
      'p90 ${pct(ms, .9).toStringAsFixed(1)} ms, max ${ms.reduce((a, b) => a > b ? a : b).toStringAsFixed(1)} ms',
    );
    expect(pct(ms, .5), lessThan(1000)); // debug-mode test timing on a shared PC: only catches a gross regression
  });
}
