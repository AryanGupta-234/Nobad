
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:material_ui/material_ui.dart' show EditableText;
import 'package:nobad_vpn_ui/engine/fake_engine.dart';
import 'package:nobad_vpn_ui/features/actions.dart';
import 'package:nobad_vpn_ui/features/home/home_screen.dart';
import 'package:nobad_vpn_ui/features/palette/palette.dart';
import 'package:nobad_vpn_ui/platform/files.dart';
import 'package:nobad_vpn_ui/platform/qr.dart';
import 'package:zxing2/qrcode.dart';

import '../support/support.dart';

const conf = '[Interface]\nPrivateKey = yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=\nAddress = 10.2.0.2/32\n\n'
    '[Peer]\nPublicKey = xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=\nAllowedIPs = 0.0.0.0/0\nEndpoint = 203.0.113.9:51820\n';

Uint8List qrPng(String text) {
  final code = Encoder.encode(text, ErrorCorrectionLevel.l);
  final m = code.matrix!;
  const scale = 6, quiet = 4;
  final size = (m.width + 2 * quiet) * scale;
  final pic = img.Image(width: size, height: size);
  img.fill(pic, color: img.ColorRgb8(255, 255, 255));
  for (var y = 0; y < m.height; y++) {
    for (var x = 0; x < m.width; x++) {
      if (m.get(x, y) == 1) {
        img.fillRect(pic, x1: (x + quiet) * scale, y1: (y + quiet) * scale, x2: (x + quiet + 1) * scale - 1,
            y2: (y + quiet + 1) * scale - 1, color: img.ColorRgb8(0, 0, 0));
      }
    }
  }
  return Uint8List.fromList(img.encodePng(pic));
}

void main() {
  setUpAll(loadWindowsFonts);

  group('palette ranking (palette.js)', () {
    test('substring, word start, initials, letters in order', () {
      expect(paletteScore('kill', 'Kill switch: turn on'), greaterThan(paletteScore('switch', 'Kill switch: turn on')));
      expect(paletteScore('switch', 'Kill switch: turn on'), greaterThanOrEqualTo(700));
      expect(paletteScore('ks', 'Kill Switch'), greaterThan(700));
      expect(paletteScore('xyz', 'Kill switch'), 0);
      expect(paletteScore('', 'anything'), 1);
    });
  });

  testWidgets('Ctrl+K finds a server and Enter connects to it', (tester) async {
    final e = FakeEngine(connectDelay: const Duration(milliseconds: 10));
    await pumpApp(tester, e);
    await settle(tester);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.keyK);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await settle(tester);
    expect(find.byType(CommandPalette), findsOneWidget);
    await tester.enterText(find.descendant(of: find.byType(CommandPalette), matching: find.byType(EditableText)), 'nl free');
    await settle(tester);
    expect(find.text('Connect to NL-FREE-12'), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await settle(tester);
    expect(e.calls.firstWhere((c) => c.$1 == 'connect').$2, {'name': 'NL-FREE-12'});
    await tester.pump(const Duration(milliseconds: 50));
    e.dispose();
  });

  testWidgets('a site becomes "Investigate", opening Intel with it', (tester) async {
    final e = FakeEngine();
    await pumpApp(tester, e);
    await settle(tester);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.keyK);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await settle(tester);
    await tester.enterText(find.descendant(of: find.byType(CommandPalette), matching: find.byType(EditableText)), 'example.com');
    await settle(tester);
    expect(find.text('Investigate “example.com”'), findsOneWidget);
    await tester.tap(find.text('Investigate “example.com”'));
    await settle(tester);
    expect(e.calls.where((c) => c.$1 == 'ni_investigate').single.$2, {'target': 'example.com'});
    await tester.pump(const Duration(seconds: 7));
    e.dispose();
  });

  testWidgets('the rail has every screen, Ctrl+1..8', (tester) async {
    final e = FakeEngine();
    await pumpApp(tester, e);
    await settle(tester);
    for (final label in ['Home', 'Servers', 'Speed', 'Network', 'Intel', 'Stream', 'Activity', 'Settings']) {
      expect(find.text(label), findsWidgets, reason: label);
    }
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.digit7);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await settle(tester);
    expect(find.text('ACTIVITY'), findsOneWidget);
    await tester.pump(const Duration(seconds: 3));
    e.dispose();
  });

  test('a QR picture gives back its config', () {
    expect(decodeQr(qrPng(conf)), conf);
    expect(decodeQr(Uint8List.fromList([1, 2, 3])), isNull);
    expect(isImageName('wg.PNG'), isTrue);
    expect(isImageName('wg.conf'), isFalse);
  });

  testWidgets('a drop reaches the window; nothing usable says what to drop', (tester) async {
    final e = FakeEngine();
    await pumpApp(tester, e);
    await settle(tester);
    final msg = const StandardMethodCodec().encodeMethodCall(const MethodCall('dropped', [r'C:\nowhere\x.exe']));
    await tester.binding.defaultBinaryMessenger.handlePlatformMessage('nobad/drop', msg, (_) {});
    await settle(tester);
    expect(find.text('Drop WireGuard .conf files or a QR picture.'), findsOneWidget);
    expect(e.calls.where((c) => c.$1 == 'import'), isEmpty);
    await tester.pump(const Duration(seconds: 7));
    e.dispose();
  });

  testWidgets('picked or dropped files: configs as text, a QR picture named first', (tester) async {
    final e = FakeEngine();
    await pumpApp(tester, e);
    await settle(tester);
    final ctx = tester.element(find.byType(HomeScreen));
    final png = qrPng(conf);
    final done = importPicked(ctx, [const PickedFile('home.conf', conf), PickedFile('qr.png', '', bytes: png)]);
    await settle(tester);
    expect(find.text('Name this server'), findsOneWidget);
    await tester.enterText(find.byType(EditableText).last, 'From-QR');
    await tester.tap(find.text('OK'));
    await settle(tester);
    await done;
    final imports = e.calls.where((c) => c.$1 == 'import').map((c) => c.$2).toList();
    expect(imports, [
      {'name': 'home.conf', 'content': conf},
      {'name': 'From-QR', 'content': conf},
    ]);
    await tester.pump(const Duration(seconds: 7));
    e.dispose();
  });
}
