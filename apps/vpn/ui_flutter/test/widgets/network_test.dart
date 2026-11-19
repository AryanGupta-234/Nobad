import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_vpn_ui/app/scope.dart';
import 'package:nobad_vpn_ui/app/theme/colors.dart';
import 'package:nobad_vpn_ui/app/theme/theme.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/features/network/network_screen.dart';
import 'package:nobad_vpn_ui/platform/files.dart';
import 'package:nobad_vpn_ui/state/vpn_controller.dart';

import '../support/support.dart';

final _report = {
  'ok': true, 'network': 'Cafe-WiFi', 'kind': 'wifi', 'grade': 'D', 'score': 48, 'vpn_connected': false,
  'trusted': false, 'ts': DateTime.now().millisecondsSinceEpoch / 1000 - 30, 'took_s': 9.4,
  'summary': 'The router answers from two different hardware addresses.',
  'checks': [
    {'id': 'arp-spoof', 'title': 'Router identity (ARP)', 'state': 'fail', 'points': 40, 'detail': 'Two devices claim the router',
        'evidence': ['192.168.1.1 is at 30:bd:13:2f:00:28 and 9a:01:22:00:11:aa']},
    {'id': 'dns', 'title': 'DNS answers', 'state': 'pass', 'points': 0, 'detail': '', 'evidence': []},
  ],
};

class _Fake extends FakeEngine {
  final asked = <(String, Map<String, Object?>)>[];
  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) async {
    asked.add((method, params));
    if (method == 'state') return {...demoState(), 'eviltwin': null};
    if (const {'network_diagnose', 'flush_dns', 'valorant_probe', 'gaming_probe', 'et_run', 'reach_test'}.contains(method)) {
      return {'ok': true};
    }
    return super.call(method, params);
  }
}

Future<_Fake> _pump(WidgetTester tester) async {
  tester.view.physicalSize = const Size(900, 2600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final e = _Fake();
  await tester.pumpWidget(MaterialApp(
    theme: nbTheme(NbColors.dark),
    home: MediaQuery(
      data: const MediaQueryData(disableAnimations: true),
      child: AppScope(
        engine: e,
        vpn: VpnController(e),
        window: FakeWindow(),
        nav: AppNav(),
        files: const NoFilePicker(),
        child: const Material(child: NetworkScreen()),
      ),
    ),
  ));
  await tester.pump();
  await tester.pump();
  return e;
}

Future<void> two(WidgetTester tester) async {
  await tester.pump();
  await tester.pump();
}

void main() {
  testWidgets('Evil Twin: empty, then a D grade with its failed check and the Connect advice', (tester) async {
    final e = await _pump(tester);
    expect(find.text('NETWORK'), findsOneWidget);
    expect(find.text('Runs by itself whenever you join a network. Press Check now to grade this one.'), findsOneWidget);
    await tester.tap(find.text('Check now'));
    await two(tester);
    expect(e.asked.map((x) => x.$1), contains('et_run'));
    expect(find.text('Checking DNS, the router, the Wi-Fi and HTTPS…'), findsOneWidget);
    e.emit('et_report', _report);
    await two(tester);
    expect(find.text('Risky: use the VPN'), findsOneWidget);
    expect(find.text('Router identity (ARP)'), findsOneWidget);
    expect(find.text('DNS answers'), findsNothing); // problems only
    expect(find.text("Don't sign in to anything on this network without the VPN."), findsOneWidget);
    await tester.tap(find.text('Show all checks (2)'));
    await two(tester);
    expect(find.text('DNS answers'), findsOneWidget);
    e.dispose();
  });

  testWidgets('network health: plain-English issues, metrics, and Clear DNS cache', (tester) async {
    final e = await _pump(tester);
    expect(find.text('Run a check to see what is working and what may need attention.'), findsOneWidget);
    await tester.tap(find.text('Run network check'));
    await two(tester);
    expect(find.text('Checking router, internet and DNS…'), findsOneWidget);
    e.emit('network_diagnose', {
      'ok': true, 'gateway': '192.168.1.1', 'gateway_ping': {'rtt': 3.0, 'loss': 0}, 'internet_ping': {'rtt': 210.0, 'loss': 0},
      'dns_ms': 40, 'dns_ok': true,
      'issues': [{'level': 'warn', 'title': 'Internet response is slow', 'simple': 'It takes a while.', 'impact': 'Lag.',
          'suggestion': 'Pause large downloads.'}],
    });
    await two(tester);
    expect(find.text('Internet response is slow'), findsOneWidget);
    expect(find.textContaining('Try this: Pause large downloads.'), findsOneWidget);
    expect(find.text('210 ms'), findsOneWidget);
    expect(find.text('40 ms'), findsOneWidget);
    await tester.tap(find.text('Clear DNS cache'));
    await two(tester);
    expect(e.asked.map((x) => x.$1), contains('flush_dns'));
    e.dispose();
  });

  testWidgets('VALORANT rows and summary; a custom endpoint goes as {host}', (tester) async {
    final e = await _pump(tester);
    await tester.tap(find.text('Refresh all'));
    await two(tester);
    e.emit('valorant_start', {'total': 2});
    e.emit('valorant_result', {'region': 'AP', 'name': 'Mumbai', 'kind': 'riot-edge', 'rtt': 31, 'method': 'ICMP',
        'target': '43.229.65.1', 'note': 'Best response among community-reported Riot edge IPs'});
    e.emit('valorant_done', {'count': 2, 'reachable': 1, 'best': {'rtt': 31, 'name': 'Mumbai'}, 'note': 'Estimates only.'});
    await two(tester);
    expect(find.text('AP · Mumbai'), findsOneWidget);
    expect(find.text('31 ms'), findsNWidgets(2));
    expect(find.text('Estimates only.'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'eu.example.net');
    await tester.tap(find.text('Test custom'));
    await two(tester);
    expect(e.asked.last.$1, 'gaming_probe');
    expect(e.asked.last.$2, {'host': 'eu.example.net'});
    e.emit('gaming_probe', {'ok': false, 'error': 'That server name could not be found. Check the address and try again.'});
    await two(tester);
    expect(find.text('Could not test this address'), findsOneWidget);
    e.dispose();
  });

  testWidgets('connectivity: each service with its route and the plain explanation', (tester) async {
    final e = await _pump(tester);
    await tester.tap(find.text('Test'));
    await two(tester);
    e.emit('reach_report', {
      'adapt': true,
      'services': [
        {'id': 'ip', 'label': 'Exit address lookup', 'status': 'ok', 'route': 'direct', 'explain': 'Works directly.'},
        {'id': 'wg', 'label': 'WireGuard download', 'status': 'unreachable', 'route': null,
            'explain': 'Not reachable on this network by any route. Connecting the VPN usually helps.'},
      ],
    });
    await two(tester);
    expect(find.text('Exit address lookup'), findsOneWidget);
    expect(find.text('unreachable'), findsOneWidget);
    expect(find.text('Not reachable on this network by any route. Connecting the VPN usually helps.'), findsOneWidget);
    e.dispose();
  });
}
