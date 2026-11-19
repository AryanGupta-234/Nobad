import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_vpn_ui/app/scope.dart';
import 'package:nobad_vpn_ui/app/theme/colors.dart';
import 'package:nobad_vpn_ui/app/theme/theme.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/features/intel/network_intel_screen.dart';
import 'package:nobad_vpn_ui/platform/files.dart';
import 'package:nobad_vpn_ui/state/vpn_controller.dart';

import '../support/support.dart';

/// Answers ni_* like the engine: the call starts the work, the result comes as an event.
class _Fake extends FakeEngine {
  final asked = <(String, Map<String, Object?>)>[];
  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) async {
    if (!method.startsWith('ni_')) return super.call(method, params);
    asked.add((method, params));
    switch (method) {
      case 'ni_overview':
        Future.microtask(() => emit('ni_overview', {
          'ok': true,
          'ts': 0,
          'took_s': 1.2,
          'snapshot': {
            'primary': 3,
            'v4_available': true,
            'v6_available': false,
            'adapters': [
              {'index': 3, 'name': 'Wi-Fi', 'status': 'Up', 'role': 'uplink', 'gateways4': ['192.168.1.1'], 'dns4': ['192.168.1.1'],
                  'dns6': [], 'dhcp_dns': ['192.168.1.1'], 'ipv4': [], 'ipv6': []},
            ],
            'doh_templates': [],
          },
          'baseline': {'known': true, 'seen': 4},
          'resolvers': [{'group': 'network', 'ip': '192.168.1.1', 'ok': true, 'rtt_ms': 9}],
          'findings': [],
        }));
      case 'ni_investigate':
        if ((params['target'] as String).isEmpty) return {'ok': false, 'error': 'Enter a site name'};
        Future.microtask(() => emit('ni_investigation', {
          'ok': true,
          'id': '7',
          'target': params['target'],
          'path': '/',
          'status': 'blocked',
          'verdict': 'dns-filtering',
          'affected': true,
          'ts': 0,
          'took_s': 3,
          'steps': [{'step': 'dns', 'state': 'fail', 'detail': 'sinkhole 0.0.0.0'}],
          'recommendations': [{'id': 'fix', 'text': 'Switch to an independent resolver.', 'action': 'dns_fix'}],
          'fixable': {'ok': true, 'reasons': []},
          'findings': [
            {'title': 'Your network answers with a sinkhole', 'severity': 'bad', 'confidence': .82, 'confidence_label': 'high',
                'layer': 'dns', 'evidence': ['192.168.1.1 → 0.0.0.0'], 'recommend': []},
          ],
          'data': {'matrix': []},
        }));
      case 'ni_fix':
        Future.microtask(() {
          emit('ni_fix_start', {'auto': false});
          emit('ni_fix', {'state': 'applied', 'ok': true, 'servers': ['1.1.1.1'], 'adapter': 'Wi-Fi', 'entry': 'ab12', 'reasons': []});
        });
      case 'ni_history':
        return {'ok': true, 'enabled': true, 'items': [{'ts': 0, 'kind': 'investigate', 'target': 'example.com', 'verdict': 'ok'}]};
    }
    return {'ok': true};
  }
}

late VpnController _vpn;

Future<_Fake> _pumpIntel(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1100, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final e = _Fake();
  final vpn = _vpn = VpnController(e);
  addTearDown(vpn.dispose);
  await tester.pumpWidget(MaterialApp(
    theme: nbTheme(NbColors.dark),
    home: MediaQuery(
      data: const MediaQueryData(disableAnimations: true, size: Size(1100, 900)),
      child: AppScope(
        engine: e,
        vpn: vpn,
        window: FakeWindow(),
        nav: AppNav(),
        files: const NoFilePicker(),
        child: const Material(child: NetworkIntelScreen()),
      ),
    ),
  ));
  await settle(tester);
  return e;
}

void main() {
  testWidgets('the overview runs once when the screen opens and shows what was measured', (tester) async {
    final e = await _pumpIntel(tester);
    expect(e.asked.where((x) => x.$1 == 'ni_overview').length, 1);
    expect(find.text('NETWORK INTELLIGENCE'), findsOneWidget);
    expect(find.text('Nothing unusual found'), findsOneWidget);
    expect(find.text('seen 4×'), findsOneWidget);
    expect(find.text('Fix my internet'), findsOneWidget);
    await tester.pump(const Duration(seconds: 7));
  });

  testWidgets('investigate a site: verdict, evidence, Fix DNS safely asks first, then the result and Undo', (tester) async {
    final e = await _pumpIntel(tester);
    await tester.tap(find.text('Sites'));
    await settle(tester);
    expect(find.text("Enter a site that doesn't open (or any site) to see what your network does with it."), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, 'blocked.example');
    await tester.tap(find.text('Investigate'));
    await settle(tester);
    expect(e.asked.last.$1, 'ni_investigate');
    expect(e.asked.last.$2, {'target': 'blocked.example'});
    expect(find.text('Blocked by DNS'), findsOneWidget);
    expect(find.text('Your network answers with a sinkhole'), findsOneWidget);
    expect(find.text('high · 82%'), findsOneWidget);
    await tester.tap(find.text('Fix DNS safely').first);
    await settle(tester);
    expect(e.asked.any((x) => x.$1 == 'ni_fix'), isFalse); // the confirmation comes first
    await tester.tap(find.text('Fix DNS safely').last);
    await settle(tester);
    expect(e.asked.last.$1, 'ni_fix');
    expect(e.asked.last.$2, {'id': '7'});
    expect(find.textContaining('Fixed · 1.1.1.1 on Wi-Fi'), findsOneWidget);
    await tester.tap(find.text('Undo this change'));
    await settle(tester);
    expect(e.asked.last.$1, 'ni_rollback');
    expect(e.asked.last.$2, {'entry': 'ab12'});
    await tester.pump(const Duration(seconds: 7));
  });

  testWidgets('an engine refusal is said, the busy line ends', (tester) async {
    await _pumpIntel(tester);
    await tester.tap(find.text('Sites'));
    await settle(tester);
    await tester.tap(find.text('Investigate'));
    await settle(tester);
    expect(_vpn.toasts.last.text, 'Enter a site name');
    expect(find.text('Testing DNS, connection, secure connection and the page…'), findsNothing);
    await tester.pump(const Duration(seconds: 7));
  });

  testWidgets('DNS lookup sends the chosen types; history loads', (tester) async {
    final e = await _pumpIntel(tester);
    await tester.tap(find.text('DNS'));
    await settle(tester);
    await tester.enterText(find.byType(TextField).first, 'example.com');
    await tester.tap(find.text('MX'));
    await tester.tap(find.text('Look up'));
    await settle(tester);
    expect(e.asked.last.$1, 'ni_lookup');
    expect(e.asked.last.$2, {'name': 'example.com', 'types': ['A', 'AAAA', 'CNAME', 'MX']});
    await tester.tap(find.text('History'));
    await settle(tester);
    expect(find.textContaining('example.com · ok', findRichText: true), findsOneWidget);
    await tester.pump(const Duration(seconds: 7));
  });
}
