import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/models_info.dart';

import '../support/fake_engine.dart';

Future<void> openModels(WidgetTester tester, FakeEngine engine) async {
  await pumpApp(tester, engine, size: const Size(1180, 1400));
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
  await tester.tap(find.textContaining('Models').last);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('every model with its facts, the recommended tier, and text models grouped by language', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    expect(find.text('Recommended for this PC: Balanced'), findsOneWidget);
    expect(find.text('multilingual-e5-small'), findsOneWidget);
    expect(find.text('LaBSE'), findsOneWidget);
    expect(find.text('SigLIP 2 base'), findsOneWidget);
    expect(find.text('MANY LANGUAGES'), findsOneWidget);
    expect(find.text('HINDI + ENGLISH'), findsOneWidget);
    expect(find.text('Needs 16 GB of memory and 8 cores (or a graphics card with 4 GB for DirectML)'), findsWidgets);
    expect(find.textContaining('Measured: 80% in the top 5'), findsOneWidget);
  });

  testWidgets('the language focus changes the recommendation only', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    await tester.tap(find.text('English first'));
    await tester.pumpAndSettle();
    expect(engine.modelsInfo.languageFocus, LanguageFocus.english);
    expect(engine.modelsInfo.models.firstWhere((m) => m.recommended && m.feature == 'text').id, 'bge-small-en-v1.5');
    expect(engine.modelsInfo.models.firstWhere((m) => m.feature == 'text' && m.state == ModelUseState.active).id,
        'minilm-l6-v2');
  });

  testWidgets('a download asks first; "Not now" downloads nothing, "Download" sends the consent', (tester) async {
    final engine = FakeEngine();
    await openModels(tester, engine);
    final button = find.text('Download…').first;
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.textContaining('Download multilingual-e5-small?'), findsOneWidget);
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(engine.modelsInfo.models.firstWhere((m) => m.id == 'multilingual-e5-small').state,
        ModelUseState.notDownloaded);
    await tester.tap(button);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Download'));
    await tester.pumpAndSettle();
    expect(engine.modelsInfo.models.firstWhere((m) => m.id == 'multilingual-e5-small').state,
        ModelUseState.downloading);
  });

  testWidgets('an older engine: says so, and offers the older downloads', (tester) async {
    final engine = FakeEngine()..old = true;
    await openModels(tester, engine);
    expect(find.textContaining('needs a newer engine'), findsOneWidget);
    expect(find.text('Allow the one-time model download'), findsOneWidget);
    expect(find.text('multilingual-e5-small'), findsNothing);
  });
}
