import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_vpn_ui/app/scope.dart';
import 'package:nobad_vpn_ui/app/theme/colors.dart';
import 'package:nobad_vpn_ui/app/theme/theme.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/features/activity/activity_screen.dart';
import 'package:nobad_vpn_ui/platform/files.dart';
import 'package:nobad_vpn_ui/state/vpn_controller.dart';

import '../support/support.dart';

final _session = {'name': 'JP-FREE-3', 'start': 1763540000, 'secs': 3723, 'rx': 150000000, 'tx': 12000000, 'peak_bps': 8.4e6};

class _Fake extends FakeEngine {
  _Fake({this.connected = true});
  final bool connected;
  final int sessions = 9;
  final asked = <(String, Map<String, Object?>)>[];
  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) async {
    asked.add((method, params));
    if (method == 'state') {
      return {
        ...demoState(connected: connected),
        'home': {'ip': '198.51.100.4', 'country': 'IN'},
        'exit': connected ? {'ip': '203.0.113.7', 'city': 'Tokyo', 'region': 'Tokyo', 'country': 'JP', 'org': 'AS9009 M247'} : null,
        'sessions': [_session],
      };
    }
    if (method == 'usage') {
      return {
        'ok': true, 'days': params['days'],
        'totals': {'rx': 3e9, 'tx': 2e8, 'secs': 7200, 'sessions': 2},
        'daily': [{'day': '2026-11-18', 'rx': 1e9, 'tx': 1e8}, {'day': '2026-11-19', 'rx': 2e9, 'tx': 1e8}],
        'sessions': [for (var i = 0; i < sessions; i++) {..._session, 'name': 'S$i'}],
        'speed': [{'ts': 1763540000, 'mbps': 42.0}, {'ts': 1763541000, 'mbps': 61.5}],
        'servers': [{'name': 'JP-FREE-3', 'rx': 2e9, 'tx': 1e8, 'sessions': 5}],
      };
    }
    return super.call(method, params);
  }
}

Future<_Fake> _pump(WidgetTester tester, _Fake e) async {
  tester.view.physicalSize = const Size(900, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
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
        child: const Material(child: ActivityScreen()),
      ),
    ),
  ));
  await tester.pump();
  await tester.pump();
  return e;
}

void main() {
  testWidgets('connected: the protection check, session, exit and recent sessions', (tester) async {
    final e = await _pump(tester, _Fake());
    expect(find.text('ACTIVITY'), findsOneWidget);
    expect(find.text('Tunnel active'), findsOneWidget);
    expect(find.text('Exit differs from real IP'), findsOneWidget);
    expect(find.text('changed'), findsOneWidget);
    e.emit('traffic', {'rx_bps': 1e6, 'tx_bps': 1e5, 'rx_total': 5000000, 'tx_total': 700000, 'hs_age': 12, 'endpoint': '146.70.205.2:51820'});
    await tester.pump();
    await tester.pump();
    expect(find.text('6/7 checks'), findsOneWidget); // JP-FREE-3 doesn't route IPv6
    expect(find.text('Mostly protected'), findsOneWidget);
    expect(find.text('IPv6 may leak'), findsOneWidget);
    expect(find.text('146.70.205.2:51820'), findsOneWidget);
    expect(find.text('12 s ago'), findsNWidgets(2));
    expect(find.text('AS9009 M247'), findsOneWidget);
    expect(find.text('MTU 1380 · keepalive 25'), findsOneWidget);
    e.dispose();
  });

  testWidgets('not connected: plain sentences instead of empty rows', (tester) async {
    final e = await _pump(tester, _Fake(connected: false));
    expect(find.text('Connect to a server to run the protection check.'), findsOneWidget);
    expect(find.text('Endpoint, handshake, traffic and uptime appear here while you are connected.'), findsOneWidget);
    expect(find.text('On (arms when connected)'), findsOneWidget);
    e.dispose();
  });

  testWidgets('usage history: totals, by server, speed tests, sessions with Show more, and the range', (tester) async {
    final e = await _pump(tester, _Fake());
    expect(e.asked.where((x) => x.$1 == 'usage').first.$2, {'days': 30});
    expect(find.text('Downloaded'), findsWidgets);
    expect(find.text('2.8 GB'), findsOneWidget);
    expect(find.text('Latest 61.5 Mbps · best 61.5 · average 51.8'), findsOneWidget);
    expect(find.text('S7'), findsOneWidget);
    expect(find.text('S8'), findsNothing);
    await tester.tap(find.text('Show more'));
    await tester.pump();
    expect(find.text('S8'), findsOneWidget);
    await tester.tap(find.text('Last 30 days'));
    await tester.pump();
    await tester.pump();
    await tester.tap(find.text('All time').last);
    await tester.pump();
    await tester.pump();
    expect(e.asked.where((x) => x.$1 == 'usage').last.$2, {'days': 0});
    e.dispose();
  });
}
