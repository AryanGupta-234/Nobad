import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_vpn_ui/app/scope.dart';
import 'package:nobad_vpn_ui/app/theme/colors.dart';
import 'package:nobad_vpn_ui/app/theme/theme.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/features/streaming/streaming_screen.dart';
import 'package:nobad_vpn_ui/platform/files.dart';
import 'package:nobad_vpn_ui/state/vpn_controller.dart';

import '../support/support.dart';

const _rep = {
  'ok': true,
  'key': 'movie:603',
  'mode': 'full',
  'title': {
    'title': 'The Matrix',
    'year': 1999,
    'type': {'label': 'Movie', 'inferred': false},
    'genres': ['Action'],
    'runtime': 136,
    'overview': 'A hacker learns the truth.',
    'alternative_titles': [],
    'ids': {'tmdb': 603, 'imdb': 'tt0133093'},
    'tmdb_url': 'https://www.themoviedb.org/movie/603',
  },
  'availability': {
    'listed': [
      {'code': 'JP', 'name': 'Japan', 'offers': {'subscription': [8]}, 'link': 'https://www.themoviedb.org/movie/603/watch?locale=JP'},
    ],
    'not_listed': [],
    'providers': [{'id': 8, 'name': 'Netflix', 'countries': {'JP': ['subscription']}}],
    'coverage': 140,
    'coverage_known': true,
    'unknown_note': 'Countries not listed may still carry it.',
    'fetched': 0,
    'fresh': true,
  },
  'recommendation': {
    'verdict': 'ok',
    'options': [
      {'code': 'JP', 'name': 'Japan', 'server': 'JP-FREE-3', 'other_servers': [], 'offer': 'subscription', 'score': 92,
          'reasons': ['Listed on Netflix'], 'caveats': [], 'restricted': false, 'verify_services': ['netflix']},
    ],
    'listed_without_server': [],
    'servers_unknown': [],
    'disclaimer': 'Catalogues change; this is not a guarantee.',
  },
  'servers': [{'name': 'JP-FREE-3', 'country': 'JP', 'country_basis': 'ip-geolocation'}],
  'certifications': [],
};

class _Fake extends FakeEngine {
  _Fake() : super(connectDelay: const Duration(milliseconds: 10));
  final asked = <(String, Map<String, Object?>)>[];
  bool keyed = false;
  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) async {
    if (!method.startsWith('si_')) return super.call(method, params);
    asked.add((method, params));
    switch (method) {
      case 'si_status':
        return {'ok': true, 'configured': keyed, 'notice': 'This product uses the TMDB API but is not endorsed or certified by TMDB.',
            'watch_attribution': 'Streaming availability data provided by JustWatch (via TMDB).', 'cache': {'entries': 3}};
      case 'si_search':
        return {'ok': true, 'results': [
          {'key': 'movie:603', 'title': 'The Matrix', 'year': 1999, 'type': {'label': 'Movie', 'inferred': false}},
        ]};
      case 'si_title':
        Future.microtask(() {
          emit('si_title', _rep);
          emit('si_restrictions', {'key': 'movie:603', 'restrictions': {'status': 'ok', 'records': []}, 'recommendation': _rep['recommendation']});
        });
        return {'ok': true};
      case 'si_verify':
        Future.microtask(() => emit('si_verify', {'server': 'JP-FREE-3', 'country': 'JP', 'country_match': true, 'exit_country': 'JP',
            'services': [{'name': 'Netflix', 'level': 'ok', 'note': 'answered normally'}]}));
        return {'ok': true};
      case 'si_open':
        return params['confirm'] == true ? {'ok': true} : {'ok': false, 'error': 'confirm', 'host': 'example.org'};
      case 'si_key':
        keyed = true;
        return {'ok': true};
    }
    return {'ok': true};
  }
}

late VpnController _vpn;

Future<_Fake> _pumpStreaming(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1100, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final e = _Fake();
  final vpn = _vpn = VpnController(e);
  addTearDown(vpn.dispose);
  final scoped = AppScope(
    engine: e,
    vpn: vpn,
    window: FakeWindow(),
    nav: AppNav(),
    files: const NoFilePicker(),
    child: const Material(child: StreamingScreen()),
  );
  await tester.pumpWidget(MaterialApp(
    theme: nbTheme(NbColors.dark),
    builder: (context, child) => AppScope(
      engine: e,
      vpn: vpn,
      window: FakeWindow(),
      nav: AppNav(),
      files: const NoFilePicker(),
      child: MediaQuery(data: MediaQuery.of(context).copyWith(disableAnimations: true), child: child!),
    ),
    home: scoped,
  ));
  await settle(tester);
  return e;
}

void main() {
  testWidgets('without a key: works without setup, with the TMDB notice and JustWatch attribution', (tester) async {
    await _pumpStreaming(tester);
    expect(find.text('STREAMING'), findsOneWidget);
    expect(find.text('Works without setup'), findsOneWidget);
    expect(find.text('This product uses the TMDB API but is not endorsed or certified by TMDB.'), findsOneWidget);
    expect(find.text('Streaming availability data provided by JustWatch (via TMDB).'), findsOneWidget);
  });

  testWidgets('search, open a title, best match, connect then verify the exit', (tester) async {
    final e = await _pumpStreaming(tester);
    await tester.enterText(find.byType(TextField).first, 'matrix');
    await tester.tap(find.text('Search'));
    await settle(tester);
    expect(find.text('1 result for “matrix”'), findsOneWidget);
    await tester.tap(find.text('The Matrix'));
    await settle(tester);
    expect(e.asked.last.$1, 'si_title');
    expect(e.asked.last.$2, {'key': 'movie:603'});
    expect(find.text('The Matrix (1999)'), findsOneWidget);
    expect(find.text('✓ Listed on Netflix'), findsOneWidget);
    await tester.tap(find.text('Connect to JP-FREE-3'));
    await settle(tester);
    expect(e.calls.firstWhere((x) => x.$1 == 'connect').$2, {'name': 'JP-FREE-3'});
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);
    expect(e.asked.any((x) => x.$1 == 'si_verify'), isTrue);
    expect(find.text('✓ Exit address is in JP'), findsOneWidget);
    await tester.tap(find.text('Countries'));
    await settle(tester);
    expect(find.text('subscription: Netflix'), findsOneWidget);
    expect(find.text('your server'), findsOneWidget);
    await tester.pump(const Duration(seconds: 7));
  });

  testWidgets('a link to an unknown host asks first, showing the host', (tester) async {
    final e = await _pumpStreaming(tester);
    await tester.enterText(find.byType(TextField).first, 'matrix');
    await tester.tap(find.text('Search'));
    await settle(tester);
    await tester.tap(find.text('The Matrix'));
    await settle(tester);
    await tester.tap(find.text('IMDb'));
    await settle(tester);
    expect(find.textContaining('example.org'), findsOneWidget);
    await tester.tap(find.text('Open'));
    await settle(tester);
    expect(e.asked.last.$2['confirm'], true);
    expect(_vpn.toasts.last.text, 'Opening in your browser…');
    await tester.pump(const Duration(seconds: 7));
  });

  testWidgets('data sources: save a key', (tester) async {
    final e = await _pumpStreaming(tester);
    await tester.tap(find.text('Data sources'));
    await settle(tester);
    expect(find.text('Streaming data sources'), findsOneWidget);
    // the key box is the first text field in the dialog
    final fields = find.descendant(of: find.byType(Dialog), matching: find.byType(TextField));
    await tester.enterText(fields.first, 'eyJabc.def');
    await tester.tap(find.text('Save & check'));
    await settle(tester);
    expect(e.asked.where((x) => x.$1 == 'si_key').single.$2, {'key': 'eyJabc.def'});
    expect(find.text('Saved. You can search now.'), findsOneWidget);
  });
}
