import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_vpn_ui/app/scope.dart';
import 'package:nobad_vpn_ui/app/theme/colors.dart';
import 'package:nobad_vpn_ui/app/theme/theme.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/features/speed/speed_screen.dart';
import 'package:nobad_vpn_ui/platform/files.dart';
import 'package:nobad_vpn_ui/state/vpn_controller.dart';

import '../support/support.dart';

class _Fake extends FakeEngine {
  final asked = <String>[];
  @override
  Future<Object?> call(String method, [Map<String, Object?> params = const {}]) async {
    asked.add(method);
    if (method == 'speedtest' || method == 'streamcheck') return {'ok': true};
    return super.call(method, params);
  }
}

Future<_Fake> _pump(WidgetTester tester) async {
  tester.view.physicalSize = const Size(900, 1600);
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
        child: const Material(child: SpeedScreen()),
      ),
    ),
  ));
  await tester.pump();
  return e;
}

void main() {
  testWidgets('speed test: runs, shows the live value, then the result and which video quality it carries', (tester) async {
    final e = await _pump(tester);
    expect(find.text('SPEED'), findsOneWidget);
    await tester.tap(find.text('Run speed test'));
    await tester.pump();
    await tester.pump();
    expect(e.asked, contains('speedtest'));
    expect(find.text('Testing…'), findsWidgets);
    e.emit('speed', {'phase': 'run', 'mbps': 12.3, 'pct': 40});
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('12.3'), findsOneWidget);
    e.emit('speed_done', {'mbps': 18.0, 'secs': 4.2});
    await tester.pump();
    await tester.pump();
    expect(find.text('Run speed test'), findsOneWidget);
    expect(find.text('18.0 Mbps'), findsNWidgets(2)); // the gauge and the launch card's Speed test tile
    e.emit('speed_done', {'error': 'URLError: offline'});
    await tester.pump();
    await tester.pump();
    expect(find.text('Test failed'), findsWidgets);
    e.dispose();
  });

  testWidgets('services: each answer appears with its note; the honest note is always there', (tester) async {
    final e = await _pump(tester);
    expect(find.text("Reachable means the site answered from this exit. It doesn't guarantee a particular title will play."),
        findsOneWidget);
    expect(find.text('Press Check to test streaming sites through your current connection.'), findsOneWidget);
    await tester.tap(find.text('Check'));
    await tester.pump();
    await tester.pump();
    expect(e.asked, contains('streamcheck'));
    e.emit('stream_start', {});
    e.emit('stream', {'id': 'netflix', 'name': 'Netflix', 'level': 'warn', 'ms': 210, 'note': 'Originals only (or VPN detected)'});
    e.emit('stream', {'id': 'youtube', 'name': 'YouTube', 'level': 'ok', 'ms': 90, 'note': 'Reachable'});
    e.emit('stream_done', {});
    await tester.pump();
    await tester.pump();
    expect(find.text('Originals only (or VPN detected)'), findsOneWidget);
    expect(find.text('90 ms'), findsOneWidget);
    expect(find.text('1 / 2 reachable'), findsOneWidget);
    e.dispose();
  });

  testWidgets('launch diagnostics follow the launch checks\' events', (tester) async {
    final e = await _pump(tester);
    expect(find.text('Starting'), findsOneWidget);
    e.emit('ipinfo', {'ip': '203.0.113.7'});
    e.emit('network_diagnose', {'issues': [{'level': 'good', 'title': 'Your basic connection looks healthy'}]});
    e.emit('valorant_start', {'total': 12});
    e.emit('valorant_done', {'count': 12, 'reachable': 10, 'best': {'rtt': 31, 'name': 'Mumbai'}});
    await tester.pump();
    await tester.pump();
    expect(find.text('203.0.113.7'), findsOneWidget);
    expect(find.text('Looks healthy'), findsOneWidget);
    expect(find.text('Best 31 ms · Mumbai'), findsOneWidget);
    expect(find.text('3 / 5 complete'), findsOneWidget);
    e.dispose();
  });
}
