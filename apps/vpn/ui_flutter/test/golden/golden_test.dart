// Pictures of every screen, dark and light, at the default window size, drawn with the real Windows fonts and the
// live map at a fixed time (test/support). Update with: flutter test --update-goldens test/golden
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_vpn_ui/app/app.dart';
import 'package:nobad_vpn_ui/app/scope.dart';
import 'package:nobad_vpn_ui/engine/engine.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/features/onboarding/free_servers.dart';

import '../support/support.dart';

Map<String, Object?> themed(Map<String, Object?> s, String theme) =>
    {...s, 'settings': {...(s['settings'] as Map), 'theme': theme}};

Future<void> shoot(WidgetTester tester, String name) async {
  for (var i = 0; i < 3; i++) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 120))); // the map's image
    await tester.pump(const Duration(milliseconds: 50));
  }
  await tester.runAsync(() async {
    for (final e in find.byType(Image).evaluate()) {
      await precacheImage((e.widget as Image).image, e);
    }
  });
  await tester.pump(const Duration(milliseconds: 400));
  await expectLater(find.byKey(shotBoundary), matchesGoldenFile('$name.png'));
}

void main() {
  setUpAll(loadWindowsFonts);
  const size = Size(1180, 760);

  for (final theme in ['dark', 'light']) {
    group(theme, () {
      testWidgets('home protected', (tester) async {
        final e = FakeEngine(state: themed(demoState(connected: true), theme));
        await pumpApp(tester, e, size: size);
        for (var i = 0; i < 40; i++) {
          e.emit('traffic', {'rx_bps': 3e6 + 6e6 * ((i * 7) % 11) / 11, 'tx_bps': 3e5 + 2e5 * ((i * 3) % 5) / 5});
        }
        await shoot(tester, 'home_protected_$theme');
        e.dispose();
      });

      testWidgets('home not protected', (tester) async {
        final e = FakeEngine(state: themed(demoState(), theme));
        await pumpApp(tester, e, size: size);
        await shoot(tester, 'home_off_$theme');
        e.dispose();
      });

      testWidgets('servers', (tester) async {
        final e = FakeEngine(state: themed(demoState(connected: true), theme));
        await pumpApp(tester, e, size: size, tab: AppTab.servers);
        await shoot(tester, 'servers_$theme');
        e.dispose();
      });

      testWidgets('settings', (tester) async {
        final e = FakeEngine(state: themed(demoState(), theme));
        await pumpApp(tester, e, size: size, tab: AppTab.settings);
        await shoot(tester, 'settings_$theme');
        e.dispose();
      });

      testWidgets('tray pop-up', (tester) async {
        final e = FakeEngine(state: themed(demoState(connected: true), theme));
        await pumpApp(tester, e, size: const Size(320, 392), mode: AppMode.mini);
        await shoot(tester, 'mini_$theme');
        e.dispose();
      });
    });
  }

  // the grid at the window's limits (window_geometry.h): edges and gutters must line up at every size
  for (final (name, sz) in [('min', const Size(960, 640)), ('max', const Size(1440, 900))]) {
    testWidgets('home protected at the $name size', (tester) async {
      final e = FakeEngine(state: demoState(connected: true));
      await pumpApp(tester, e, size: sz);
      await shoot(tester, 'home_protected_${name}_dark');
      e.dispose();
    });
  }

  testWidgets('blocked by the kill switch', (tester) async {
    final e = FakeEngine(state: {...demoState(), 'ks_active': true});
    await pumpApp(tester, e, size: size);
    await shoot(tester, 'home_blocked_dark');
    e.dispose();
  });

  testWidgets('connecting', (tester) async {
    final e = FakeEngine(state: {...demoState(), 'connecting': 'NL-FREE-12'});
    await pumpApp(tester, e, size: size);
    await shoot(tester, 'home_connecting_dark');
    e.dispose();
  });

  testWidgets('no servers yet: the free-server guide', (tester) async {
    final e = FakeEngine(state: demoState(empty: true));
    await pumpApp(tester, e, size: size);
    await shoot(tester, 'home_empty_dark');
    await tester.pump(const Duration(seconds: 7));
    e.dispose();
  });

  testWidgets('free servers dialog', (tester) async {
    final e = FakeEngine(state: demoState());
    await pumpApp(tester, e, size: size);
    showFreeServers(appNavigator.currentContext!);
    await shoot(tester, 'free_servers_dark');
    e.dispose();
  });

  testWidgets('not running', (tester) async {
    final e = FakeEngine(link: Link.offline);
    await pumpApp(tester, e, size: size);
    await shoot(tester, 'offline_dark');
    e.dispose();
  });
}
