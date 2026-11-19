import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/scope_info.dart';
import 'package:nobad_find/platform/languages.dart';
import 'package:nobad_find/state/categories.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/widgets/controls.dart';

import '../support/fake_engine.dart';

Future<void> openScope(WidgetTester tester, FakeEngine engine) async {
  await pumpApp(tester, engine, size: const Size(1180, 1600));
  await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
  await tester.sendKeyEvent(LogicalKeyboardKey.digit3);
  await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
  await tester.pumpAndSettle();
  await tester.tap(find.text('What to index'));
  await tester.pumpAndSettle();
}

void main() {
  test('scope_info and turbo_state as the engine sends them', () {
    final s = ScopeInfo.fromJson({
      'scope': 'whole_pc',
      'roots': [r'C:\'],
      'categories': [
        {
          'id': 'secrets',
          'name': 'Keys',
          'why': 'w',
          'examples': ['.ssh'],
          'included': false,
          'locked': false,
        },
        {'id': 'other_profiles', 'name': 'Others', 'locked': true, 'count': null},
        {'nope': 1},
      ],
    });
    expect(s.scope, IndexScope.wholePc);
    expect(s.categories, hasLength(2));
    expect(s.categories.first.setting, 'include_secrets');
    expect(s.categories.last.count, isNull);
    final t = TurboState.fromJson({
      'available': true,
      'enabled': true,
      'running': true,
      'volumes': [
        {'drive': r'C:\', 'ntfs': true, 'files': 5, 'usn_ok': true, 'last_scan': 1.5},
      ],
      'error': '',
    });
    expect(t.line, 'Turbo: on (C: NTFS)');
    expect(const TurboState(available: true, error: 'Windows said no.').line, 'Turbo: off. Windows said no.');
    expect(const TurboState().line, startsWith('Turbo: not available'));
  });

  test("Windows' languages suggest a focus like the engine's rule", () {
    expect(focusFromLangIds([0x0409]), 'english');
    expect(focusFromLangIds([0x0409, 0x0439]), 'hindi');
    expect(focusFromLangIds([0x0407]), 'multilingual');
  });

  test('a category is read from the filters in use', () {
    expect(SearchCategory.of(const SearchFilters(kind: 'pdf')), SearchCategory.documents);
    expect(SearchCategory.of(const SearchFilters(kind: 'audio')), SearchCategory.media);
    expect(SearchCategory.of(const SearchFilters(folder: 'downloads', kind: 'pdf')), SearchCategory.downloads);
    expect(SearchCategory.of(const SearchFilters(modified: 'week', sort: 'newest')), SearchCategory.recent);
    expect(SearchCategory.of(SearchFilters.none), SearchCategory.all);
  });

  testWidgets('every category with why and examples; secrets say names only; locked ones have no switch', (
    tester,
  ) async {
    final engine = FakeEngine();
    await openScope(tester, engine);
    expect(find.text('Keys and password stores'), findsOneWidget);
    expect(find.text('Names only: the contents of these files are never read.'), findsOneWidget);
    expect(find.text("Other people's files"), findsOneWidget);
    expect(find.byWidgetPredicate((w) => w is NbSwitch && w.label == "Other people's files"), findsNothing);
    await tester.tap(find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'App data and caches'));
    await tester.pumpAndSettle();
    expect(engine.settingsSet.last, {'include_caches': true});
    expect(find.text('96,214 in the index'), findsOneWidget);
  });

  testWidgets('turbo: the switch asks Windows; No keeps it off and says why; Yes shows the drives', (tester) async {
    final engine = FakeEngine()..turboPromptYes = false;
    await openScope(tester, engine);
    final sw = find.byWidgetPredicate((w) => w is NbSwitch && w.label == 'Turbo index');
    await tester.ensureVisible(sw);
    await tester.tap(sw);
    await tester.pumpAndSettle();
    expect(find.textContaining("Windows didn't give permission"), findsOneWidget);
    engine.turboPromptYes = true;
    await tester.tap(sw);
    await tester.pumpAndSettle();
    expect(find.text('Turbo: on (C:, D: NTFS)'), findsOneWidget);
    expect(find.text('612,408'), findsOneWidget);
  });

  testWidgets('an older engine: the older rows, and why', (tester) async {
    final engine = FakeEngine()..old = true;
    await openScope(tester, engine);
    expect(find.textContaining('needs a newer engine'), findsOneWidget);
    expect(find.text('Folders to search'), findsOneWidget);
  });
}
