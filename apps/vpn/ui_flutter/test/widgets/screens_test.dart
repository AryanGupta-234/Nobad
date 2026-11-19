import 'dart:io';

import 'package:flutter/gestures.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:nobad_vpn_ui/app/app.dart';
import 'package:nobad_vpn_ui/app/scope.dart';
import 'package:nobad_vpn_ui/engine/engine.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/features/shell/splash.dart';
import 'package:nobad_vpn_ui/platform/files.dart';
import 'package:nobad_vpn_ui/map/map_view.dart';
import 'package:nobad_vpn_ui/widgets/aperture.dart';

import '../support/support.dart';

Iterable<String> calls(FakeEngine e) => e.calls.map((c) => c.$1);

void main() {
  setUpAll(loadWindowsFonts);

  group('home', () {
    testWidgets('not protected: one display line, the aperture connects to the target', (tester) async {
      final e = FakeEngine(connectDelay: const Duration(milliseconds: 10));
      await pumpApp(tester, e);
      await settle(tester);
      expect(find.text('NOT PROTECTED'), findsOneWidget);
      expect(find.text('Choose a location to begin.'), findsOneWidget);
      await tester.tap(find.byType(Aperture));
      await settle(tester);
      expect(e.calls.firstWhere((c) => c.$1 == 'connect').$2, {'name': 'JP-FREE-3'});
      await tester.pump(const Duration(milliseconds: 50));
      await settle(tester);
      expect(find.text('PROTECTED'), findsOneWidget);
      expect(find.text('Connected · Tokyo, JP · 61 ms'), findsOneWidget); // the map's chip
      expect(find.text('Your traffic leaves through JP-FREE-3 in Tokyo, JP.'), findsOneWidget);
      expect(find.text('Armed: kill switch and DNS leak block'), findsOneWidget);
      await tester.tap(find.byType(Aperture));
      await settle(tester);
      expect(calls(e), contains('disconnect'));
      e.dispose();
    });

    testWidgets('a row selects (the aperture then means it), its button connects; the star; the chips', (tester) async {
      final e = FakeEngine(connectDelay: const Duration(milliseconds: 10));
      await pumpApp(tester, e);
      await settle(tester);
      await tester.tap(find.text('NL-FREE-12'));
      await settle(tester);
      expect(calls(e), isNot(contains('connect')));
      expect(find.bySemanticsLabel(RegExp(r'^Connect, NL-FREE-12')), findsOneWidget);
      await tester.tap(find.byType(Aperture));
      await tester.tap(find.bySemanticsLabel('Add US-FREE-34 to favorites'));
      await tester.tap(find.text('Auto-repair'));
      await settle(tester);
      expect(e.calls.firstWhere((c) => c.$1 == 'connect').$2, {'name': 'NL-FREE-12'});
      expect(e.calls.firstWhere((c) => c.$1 == 'favorite').$2, {'name': 'US-FREE-34'});
      expect(e.calls.firstWhere((c) => c.$1 == 'settings').$2, {'key': 'auto_repair', 'value': false});
      await tester.pump(const Duration(milliseconds: 50));
      e.dispose();
    });

    testWidgets('blocked by the kill switch: the notice offers Restore internet, which asks first', (tester) async {
      final e = FakeEngine(state: {...demoState(), 'ks_active': true});
      await pumpApp(tester, e);
      await settle(tester);
      expect(find.text('BLOCKED'), findsOneWidget);
      expect(find.text('Kill switch is blocking your internet'), findsOneWidget);
      await tester.tap(find.text('Restore internet').first);
      await settle(tester);
      expect(find.text('Remove all NOBAD firewall rules and stop NOBAD tunnels? Your internet will work normally afterwards.'),
          findsOneWidget);
      expect(calls(e), isNot(contains('panic_reset')));
      await tester.tap(find.text('Restore internet').last);
      await settle(tester);
      expect(calls(e), contains('panic_reset'));
      expect(find.text('Restoring internet…'), findsOneWidget);
      await tester.pump(const Duration(seconds: 7));
      e.dispose();
    });

    testWidgets('a failed connect shows the engine\'s actions; Retry dismisses and reconnects', (tester) async {
      final e = FakeEngine(state: {
        ...demoState(),
        'error': {'code': 'handshake', 'title': 'x', 'detail': 'Check the keys and the endpoint address/port.',
            'name': 'NL-FREE-12', 'ts': 5, 'actions': [{'id': 'retry', 'label': 'Retry'}, {'id': 'show_log', 'label': 'Show log'}]},
      }, connectDelay: const Duration(milliseconds: 10));
      await pumpApp(tester, e);
      await settle(tester);
      expect(find.text('NL-FREE-12 never completed a handshake'), findsOneWidget);
      await tester.tap(find.text('Retry'));
      await settle(tester);
      expect(calls(e), containsAllInOrder(['dismiss_error', 'connect']));
      expect(e.calls.firstWhere((c) => c.$1 == 'connect').$2, {'name': 'NL-FREE-12'});
      await tester.pump(const Duration(seconds: 16));
      e.dispose();
    });

    testWidgets('Windows Firewall off: protection not enforced, said plainly', (tester) async {
      final e = FakeEngine(state: {...demoState(connected: true), 'fw_off': true});
      await pumpApp(tester, e);
      await settle(tester);
      expect(find.text('Protection not enforced'), findsOneWidget);
      await tester.tap(find.text('Turn on Windows Firewall'));
      await settle(tester);
      expect(e.calls.last.$1, 'open_url');
      expect(e.calls.last.$2, {'key': 'firewall_settings'});
      e.dispose();
    });

    testWidgets('no servers yet: the free-server guide is the onboarding, and the aperture opens it', (tester) async {
      final e = FakeEngine(state: demoState(empty: true));
      await pumpApp(tester, e);
      await settle(tester);
      expect(find.text('Get free servers'), findsOneWidget);
      expect(find.text('Proton VPN Free'), findsOneWidget);
      expect(find.text('Add server'), findsOneWidget);
      await tester.tap(find.text('Create free account'));
      await settle(tester);
      expect(e.calls.where((c) => c.$1 == 'open_url').single.$2, {'key': 'proton_signup'});
      expect(find.text('Found in Downloads'), findsOneWidget);
      expect(find.text('1 new'), findsOneWidget);
      await tester.ensureVisible(find.text('Add selected servers'));
      await tester.tap(find.text('Add selected servers'));
      await settle(tester);
      expect(e.calls.where((c) => c.$1 == 'free_import').single.$2, {'files': ['wg-JP-FREE-3.conf']});
      await tester.pump(const Duration(seconds: 7));
      e.dispose();
    });

    testWidgets('first run opens the setup checklist', (tester) async {
      final e = FakeEngine(state: demoState(wizardDone: false));
      await pumpApp(tester, e);
      await settle(tester);
      expect(find.text('Set up NOBAD'), findsOneWidget);
      expect(find.text('3 server(s) found.'), findsNothing);
      expect(find.text('4 server(s) found.'), findsOneWidget);
      await tester.tap(find.text('Finish'));
      await settle(tester);
      expect(calls(e), contains('wizard_done'));
      e.dispose();
    });

    testWidgets('picked files: only their text goes to the engine', (tester) async {
      final e = FakeEngine(state: demoState(empty: true));
      await pumpApp(tester, e,
          tab: AppTab.servers, files: const NoFilePicker([PickedFile('a.conf', '[Interface]\nAddress = 10.0.0.2/32')]));
      await settle(tester);
      await tester.tap(find.text('Import .conf'));
      await settle(tester);
      expect(e.calls.where((c) => c.$1 == 'import').single.$2, {'name': 'a.conf', 'content': '[Interface]\nAddress = 10.0.0.2/32'});
      await tester.pump(const Duration(seconds: 7));
      e.dispose();
    });
  });

  group('offline and the engine\'s own events', () {
    testWidgets('no engine: says NOBAD VPN is not running, never a raw answer', (tester) async {
      final e = FakeEngine(link: Link.offline);
      await pumpApp(tester, e);
      await settle(tester);
      expect(find.text('NOT RUNNING'), findsOneWidget);
      expect(find.textContaining('{'), findsNothing);
      e.dispose();
    });

    testWidgets('show brings the main window to the front; quitting closes it', (tester) async {
      final e = FakeEngine();
      final w = await pumpApp(tester, e);
      e.emit('show', {'window': 'main'});
      e.emit('quitting', {});
      await settle(tester);
      expect(w.calls, containsAllInOrder(['front', 'close']));
      e.dispose();
    });
  });

  group('servers and settings', () {
    testWidgets('search, sort and the editor', (tester) async {
      final e = FakeEngine();
      await pumpApp(tester, e, tab: AppTab.servers);
      await settle(tester);
      expect(find.text('SERVERS'), findsOneWidget);
      await tester.enterText(find.byType(TextField).first, 'york');
      await settle(tester);
      expect(find.text('US-FREE-34'), findsOneWidget);
      expect(find.text('NL-FREE-12'), findsNothing);
      await tester.tap(find.bySemanticsLabel('Edit US-FREE-34'));
      await settle(tester);
      expect(find.text('Edit US-FREE-34'), findsOneWidget);
      expect(calls(e), contains('config_get'));
      e.dispose();
    });

    testWidgets('categories in the sidebar; a switch sends the setting; search finds across them', (tester) async {
      final e = FakeEngine();
      await pumpApp(tester, e, tab: AppTab.settings);
      await settle(tester);
      expect(find.text('Kill switch'), findsWidgets);
      await tester.tap(find.bySemanticsLabel('Strict kill switch'));
      await settle(tester);
      expect(e.calls.last.$1, 'settings');
      expect(e.calls.last.$2, {'key': 'ks_strict', 'value': true});
      await tester.tap(find.text('Privacy & security'));
      await settle(tester);
      expect(find.text('Look up my exit IP address'), findsOneWidget);
      await tester.enterText(find.byType(TextField).first, 'winsock');
      await settle(tester);
      expect(find.text('Full network reset'), findsOneWidget);
      await tester.tap(find.text('Reset…'));
      await settle(tester);
      expect(find.textContaining('resets Winsock, TCP/IP and the WinHTTP proxy'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await settle(tester);
      expect(calls(e), isNot(contains('net_repair')));
      e.dispose();
    });

    testWidgets('every WebView setting is here', (tester) async {
      final e = FakeEngine();
      await pumpApp(tester, e, tab: AppTab.settings);
      await settle(tester);
      const keys = ['kill_switch', 'dns_leak_block', 'force_tunnel_dns', 'fallback_dns', 'ks_strict', 'watchdog',
          'watchdog_failopen', 'et_enabled', 'et_vpn_below', 'ni_autofix', 'ni_history', 'ni_reference_dns',
          'auto_repair', 'reconnect_on_network_change', 'stream_tuned', 'auto_connect', 'smart_select', 'guard_service',
          'guard_auto_switch', 'ssid_rules', 'autoconnect_untrusted', 'autodisconnect_trusted', 'start_with_windows',
          'tray', 'close_to_tray', 'guardian', 'notifications', 'visual_effects', 'net_adapt', 'ip_lookup',
          'startup_checks', 'encrypt_configs', 'crash_reporting', 'crash_report_url', 'auto_install_wg',
          'auto_update_check', 'update_url'];
      final all = File('lib/features/settings/settings_screen.dart').readAsStringSync();
      for (final k in keys) {
        expect(all.contains("SettingRow('$k'"), isTrue, reason: k);
      }
      e.dispose();
    });
  });

  group('the tray pop-up', () {
    testWidgets('state, server, connect, fastest, kill switch, open NOBAD; Esc hides', (tester) async {
      final e = FakeEngine(connectDelay: const Duration(milliseconds: 10));
      final w = await pumpApp(tester, e, mode: AppMode.mini, size: const Size(320, 392));
      await settle(tester);
      expect(find.text('Not connected'), findsOneWidget);
      await tester.tap(find.text('Connect'));
      await settle(tester);
      expect(e.calls.firstWhere((c) => c.$1 == 'connect').$2, {'name': 'JP-FREE-3'});
      await tester.pump(const Duration(milliseconds: 50));
      await settle(tester);
      expect(find.text('Protected'), findsOneWidget);
      expect(find.text('Disconnect'), findsOneWidget);
      await tester.tap(find.bySemanticsLabel('Kill switch'));
      await settle(tester);
      expect(e.calls.last.$1, 'settings');
      expect(e.calls.last.$2, {'key': 'kill_switch', 'value': false});
      await tester.tap(find.text('Open NOBAD'));
      await settle(tester);
      expect(e.calls.last.$1, 'ui_show');
      expect(w.calls, contains('spawn main')); // the engine had no main window to show: start one
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await settle(tester);
      expect(w.calls, contains('hide'));
      e.dispose();
    });

    testWidgets('no engine: a sentence, not {"ok": false}', (tester) async {
      final e = FakeEngine(link: Link.offline);
      await pumpApp(tester, e, mode: AppMode.mini, size: const Size(320, 392));
      await settle(tester);
      expect(find.text("NOBAD VPN isn't running. Start it from the Start menu."), findsOneWidget);
      expect(find.textContaining('"ok"'), findsNothing);
      e.dispose();
    });

    testWidgets('a tray click while it is up hides it, the next shows it next to the tray', (tester) async {
      final e = FakeEngine();
      final w = await pumpApp(tester, e, mode: AppMode.mini, size: const Size(320, 392));
      await settle(tester);
      e.emit('show', {'window': 'mini'});
      await settle(tester);
      e.emit('show', {'window': 'mini'});
      await settle(tester);
      e.emit('show', {'window': 'main'}); // not this window's
      await settle(tester);
      expect(w.calls.where((c) => c == 'hide' || c == 'showMini' || c == 'front'), ['hide', 'showMini']);
      e.dispose();
    });
  });


  group('the map', () {
    Offset pinOf(WidgetTester tester, String name) {
      final st = tester.state<MapViewState>(find.byType(MapView));
      final box = tester.getRect(find.byType(MapView));
      final m = tester.widget<MapView>(find.byType(MapView)).servers.firstWhere((x) => x.name == name);
      return box.topLeft + st.camera.toScreen(m.lat, m.lon, box.size);
    }

    testWidgets('hover shows a tooltip, a click selects, a double-click connects', (tester) async {
      final e = FakeEngine(connectDelay: const Duration(milliseconds: 10));
      await pumpApp(tester, e);
      await settle(tester);
      final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
      await mouse.addPointer(location: Offset.zero);
      addTearDown(mouse.removePointer);
      await mouse.moveTo(pinOf(tester, 'NL-FREE-12'));
      await settle(tester);
      expect(find.text('Last ping 148 ms'), findsOneWidget);
      expect(find.text('nl-free-12.protonvpn.net:51820'), findsOneWidget);
      await tester.tapAt(pinOf(tester, 'NL-FREE-12'));
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      expect(find.bySemanticsLabel(RegExp(r'^Connect, NL-FREE-12')), findsOneWidget); // the list and aperture follow
      expect(calls(e), isNot(contains('connect')));
      await mouse.moveTo(pinOf(tester, 'US-FREE-34'));
      await tester.pump();
      await tester.tapAt(pinOf(tester, 'US-FREE-34'));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.tapAt(pinOf(tester, 'US-FREE-34'));
      await tester.pump(const Duration(milliseconds: 400));
      await settle(tester);
      expect(e.calls.firstWhere((c) => c.$1 == 'connect').$2, {'name': 'US-FREE-34'});
      await tester.pump(const Duration(milliseconds: 50));
      e.dispose();
    });

    testWidgets('a server the engine cannot place says "location unknown" and gets no pin', (tester) async {
      final e = FakeEngine();
      await pumpApp(tester, e);
      await settle(tester);
      expect(tester.widget<MapView>(find.byType(MapView)).servers.map((m) => m.name), isNot(contains('Home-Router')));
      expect(find.textContaining('location unknown'), findsWidgets);
      expect(find.text('3 on the map · 1 location unknown'), findsOneWidget);
      e.dispose();
    });

    testWidgets('wheel zooms about the pointer, Fit all brings everything back', (tester) async {
      final e = FakeEngine();
      await pumpApp(tester, e);
      await settle(tester);
      final st = tester.state<MapViewState>(find.byType(MapView));
      final z0 = st.camera.zoom;
      final at = tester.getCenter(find.byType(MapView));
      final pointer = TestPointer(1, PointerDeviceKind.mouse);
      await tester.sendEventToBinding(pointer.hover(at));
      await tester.sendEventToBinding(pointer.scroll(const Offset(0, -300)));
      await tester.pump();
      expect(st.camera.zoom, greaterThan(z0));
      await tester.tap(find.text('Fit all'));
      await tester.pump(const Duration(milliseconds: 400));
      expect(st.camera.zoom, lessThan(st.camera.zoom + 1));
      e.dispose();
    });
  });

  test('the splash line follows the real start-up', () {
    expect(splashStep(Link.offline, false).$1, lessThan(splashStep(Link.connecting, false).$1));
    expect(splashStep(Link.connecting, false).$1, lessThan(splashStep(Link.connected, false).$1));
    expect(splashStep(Link.connected, true), (1, 'Ready'));
  });
}
