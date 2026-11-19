import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_vpn_ui/engine/engine.dart';
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/engine/models.dart';
import 'package:nobad_vpn_ui/state/vpn_controller.dart';

void main() {
  test('state, traffic, health, probe and errors come from events', () async {
    final e = FakeEngine(connectDelay: Duration.zero);
    final vpn = VpnController(e);
    await pumpEventQueue();
    expect(vpn.state!.protection, Protection.off);
    e.emit('traffic', {'rx_bps': 1e6, 'tx_bps': 2e5});
    e.emit('probe', {'name': 'Home-Router', 'ping': {'rtt': 9.0, 'loss': 0}});
    e.emit('health', {'rtt': 33.0, 'loss': 0, 'jitter': 1.0, 'q': 'great'});
    e.emit('error_action', {'code': 'handshake', 'title': 'x', 'name': 'JP-FREE-3', 'ts': 1, 'actions': []});
    await pumpEventQueue();
    expect(vpn.samples.rx.last, 1e6);
    expect(vpn.state!.region('Home-Router')!.ping!.rtt, 9);
    expect(vpn.state!.health!.rtt, 33);
    expect(vpn.state!.error!.code, 'handshake');
    expect(vpn.state!.error!.transient, isTrue);
    vpn.dispose();
    e.dispose();
  });

  test('the aperture connects to the target and disconnects; samples clear when the tunnel goes', () async {
    final e = FakeEngine(connectDelay: Duration.zero);
    final vpn = VpnController(e);
    await pumpEventQueue();
    await vpn.toggle();
    await pumpEventQueue();
    await Future<void>.delayed(Duration.zero);
    expect(e.calls.where((c) => c.$1 == 'connect').single.$2, {'name': 'JP-FREE-3'});
    expect(vpn.state!.protection, Protection.protected);
    e.emit('traffic', {'rx_bps': 5.0, 'tx_bps': 1.0});
    await pumpEventQueue();
    await vpn.toggle();
    await pumpEventQueue();
    expect(vpn.state!.protection, Protection.off);
    expect(vpn.samples.rx, isEmpty);
    vpn.dispose();
    e.dispose();
  });

  test('an {ok: false} answer becomes a toast with the sentence; offline says NOBAD is not running', () async {
    final e = FakeEngine();
    final vpn = VpnController(e);
    await pumpEventQueue();
    await vpn.connect('Nowhere');
    expect(vpn.toasts.last.text, 'Unknown server');
    e.setLink(Link.offline);
    await vpn.act(e.disconnect);
    expect(vpn.toasts.last.text, contains("isn't running"));
    vpn.dispose();
    e.dispose();
  });

  test('busy keys end with task_done; its error is shown', () async {
    final e = FakeEngine();
    final vpn = VpnController(e);
    await pumpEventQueue();
    await vpn.act(e.fastest, busyKey: 'fastest');
    expect(vpn.busy, contains('fastest'));
    e.emit('task_done', {'key': 'fastest', 'error': 'RuntimeError: no servers answered'});
    await pumpEventQueue();
    expect(vpn.busy, isEmpty);
    expect(vpn.toasts.last.text, 'RuntimeError: no servers answered');
    vpn.dispose();
    e.dispose();
  });

  test('show and quitting events reach the window', () async {
    final e = FakeEngine();
    final shown = <String>[];
    var quit = false;
    final vpn = VpnController(e, onShow: shown.add, onQuitting: () => quit = true);
    e.emit('show', {'window': 'mini'});
    e.emit('quitting', {});
    await pumpEventQueue();
    expect(shown, ['mini']);
    expect(quit, isTrue);
    vpn.dispose();
    e.dispose();
  });

  test('formats', () {
    expect(rate(12.4e6), '12.4 Mbps');
    expect(rate(512e3), '512 kbps');
    expect(rate(80), '80 bps');
    expect(bytes(1536), '1.5 KB');
    expect(ms(null), '—');
    expect(uptime(100, DateTime.fromMillisecondsSinceEpoch(100000 + 3723000)), '1h 2m');
  });

  test('state model: protection, target and defaults for odd values', () {
    final s = VpnState.fromJson(demoState());
    expect(s.protection, Protection.off);
    expect(s.target, 'JP-FREE-3');
    expect(VpnState.fromJson({...demoState(), 'ks_active': true}).protection, Protection.blocked);
    expect(VpnState.fromJson({...demoState(), 'connecting': 'NL-FREE-12'}).protection, Protection.connecting);
    final odd = VpnState.fromJson({'regions': 'no', 'settings': 5, 'connected': 'yes', 'error': {'actions': 'x'}});
    expect(odd.regions, isEmpty);
    expect(odd.connected, isFalse);
    expect(odd.error!.actions, isEmpty);
  });
}
