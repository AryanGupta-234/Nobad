/// The flows several screens share: restore internet, network repair, importing servers (files, a link, pasted
/// text), the config editor. Texts are the WebView UI's (nobadvpn/ui/app_ext.js), so nothing users learned changes.
library;

import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../app/scope.dart';
import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import '../engine/engine.dart';
import '../engine/models.dart';
import '../platform/files.dart';
import '../platform/qr.dart';
import '../widgets/controls.dart';
import '../widgets/dialogs.dart';

/// Dialogs are built under the navigator, above AppScope: give them the scope again.
Future<T?> showScoped<T>(BuildContext context, Widget Function(BuildContext) builder) {
  final scope = AppScope.of(context);
  return showDialog<T>(
    context: context,
    builder: (ctx) => AppScope(
      engine: scope.engine,
      vpn: scope.vpn,
      window: scope.window,
      nav: scope.nav,
      files: scope.files,
      now: scope.now,
      child: Builder(builder: builder),
    ),
  );
}

Future<void> panic(BuildContext context) async {
  final vpn = AppScope.of(context).vpn;
  final ok = await confirmDialog(
    context,
    title: 'Restore internet',
    question: 'Remove all NOBAD firewall rules and stop NOBAD tunnels? Your internet will work normally afterwards.',
    yes: 'Restore internet',
    danger: true,
  );
  if (ok) await vpn.act(vpn.engine.panic, done: 'Restoring internet…');
}

const repairQuestions = {
  'undo':
      'Restore internet: removes every NOBAD firewall rule, tunnel and DNS change, so Windows is back exactly as it was before NOBAD. Nothing else is touched. Continue?',
  'quick':
      'Quick network repair: removes every NOBAD change, then flushes DNS, clears the ARP cache and renews DHCP. Your connection may blink once. Continue?',
  'full':
      'Full network reset: removes every NOBAD change, then resets Winsock, TCP/IP and the WinHTTP proxy. Windows must restart afterwards, and manually set IP addresses must be entered again. Continue?',
};

Future<void> netRepair(BuildContext context, String level) async {
  final vpn = AppScope.of(context).vpn;
  final ok = await confirmDialog(
    context,
    title: level == 'full' ? 'Full network reset' : (level == 'quick' ? 'Quick network repair' : 'Restore internet'),
    question: repairQuestions[level]!,
    yes: level == 'full' ? 'Reset' : 'Repair',
    danger: level == 'full',
  );
  if (ok) await vpn.act(() => vpn.engine.netRepair(level), busyKey: 'net_repair');
}

/// Import files picked in Windows' Open dialog; only their text goes to the engine.
Future<void> importFiles(BuildContext context) async {
  final scope = AppScope.of(context);
  final files = await scope.files.pickConfigs(scope.window.handle);
  if (files.isEmpty || !context.mounted) return;
  await importPicked(context, files);
}

/// Files dropped on the window: read here, as the user, then imported like picked ones.
Future<void> importDropped(BuildContext context, List<String> paths) async {
  final files = await readPicked(paths);
  if (!context.mounted) return;
  if (files.isEmpty) {
    AppScope.of(context).vpn.toast('Drop WireGuard .conf files or a QR picture.');
    return;
  }
  await importPicked(context, files);
}

/// Configs as text, pictures through their QR code (named by the user, like the WebView's QR import). Only text
/// ever goes to the engine; it refuses script hooks on every import.
Future<void> importPicked(BuildContext context, List<PickedFile> files) async {
  final vpn = AppScope.of(context).vpn;
  final ok = <String>[], bad = <String>[];
  for (var f in files) {
    if (f.bytes != null) {
      final text = decodeQr(f.bytes!);
      if (text == null) {
        bad.add('${f.name}: no QR code found');
        continue;
      }
      if (!context.mounted) return;
      final stem = f.name.contains('.') ? f.name.substring(0, f.name.lastIndexOf('.')) : f.name;
      final name = await askText(context, title: 'Name this server', label: 'Name',
          initial: (stem.isEmpty ? 'QR-import' : stem).substring(0, stem.length > 32 ? 32 : (stem.isEmpty ? 9 : stem.length)));
      if (name == null) continue;
      f = PickedFile(name, text);
    }
    try {
      final a = await vpn.engine.importConfig(f.name, f.text);
      a.ok ? ok.add(jStr(a.data['name'], f.name)) : bad.add('${f.name}: ${a.error}');
    } on Object catch (e) {
      bad.add('${f.name}: ${e is RpcException ? e.message : e}');
    }
  }
  if (ok.isNotEmpty) {
    vpn.toast('Imported ${ok.length}: ${ok.join(', ')}${bad.isEmpty ? '' : ' · ${bad.length} failed'}', good: true);
  } else if (bad.isNotEmpty) {
    vpn.toast(bad.first);
  }
}

Future<void> importUrl(BuildContext context) async {
  final vpn = AppScope.of(context).vpn;
  final url = await askText(context, title: 'Import from URL', label: 'HTTPS link to a .conf file', hint: 'https://');
  if (url == null) return;
  final a = await vpn.act(() => vpn.engine.importUrl(url));
  if (a != null && a.ok) vpn.toast('Imported 1: ${jStr(a.data['name'])}', good: true);
}

/// "Import QR image": pick a picture, read its QR code here.
Future<void> importQr(BuildContext context) => importFiles(context);

Future<String?> askText(BuildContext context, {required String title, required String label, String? hint, String initial = ''}) {
  final ctl = TextEditingController(text: initial);
  return showDialog<String>(
    context: context,
    builder: (context) {
      void done() => Navigator.pop(context, ctl.text.trim().isEmpty ? null : ctl.text.trim());
      return NbDialog(
        title: title,
        body: NbTextBox(controller: ctl, label: label, hint: hint, autofocus: true, maxLength: 2048, onSubmitted: (_) => done()),
        actions: [
          NbButton('Cancel', kind: NbButtonKind.ghost, onPressed: () => Navigator.pop(context)),
          NbButton('OK', onPressed: done),
        ],
      );
    },
  );
}

/// Paste a config (name + text), or edit one: keys stay hidden and are kept as they are unless replaced.
Future<void> openEditor(BuildContext context, {String? name, String prefill = ''}) =>
    showScoped<void>(context, (ctx) => ConfigEditor(name: name, prefill: prefill));

class ConfigEditor extends StatefulWidget {
  const ConfigEditor({super.key, this.name, this.prefill = ''});
  final String? name;
  final String prefill;

  @override
  State<ConfigEditor> createState() => _ConfigEditorState();
}

class _ConfigEditorState extends State<ConfigEditor> {
  late final _text = TextEditingController(text: widget.prefill);
  final _name = TextEditingController();
  Timer? _debounce;
  bool _valid = false, _encrypted = false, _loaded = false;
  List<String> _errors = const [], _warnings = const [];

  bool get _creating => widget.name == null;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final vpn = AppScope.of(context).vpn;
    if (!_creating) {
      final a = await vpn.act(() => vpn.engine.configGet(widget.name!));
      if (!mounted) return;
      if (a == null || !a.ok) return Navigator.pop(context);
      _text.text = jStr(a.data['text']);
      _encrypted = jBool(a.data['encrypted']);
    }
    setState(() => _loaded = true);
    unawaited(_check());
  }

  Future<void> _check() async {
    final vpn = AppScope.of(context).vpn;
    try {
      final a = await vpn.engine.configValidate(_creating ? '' : widget.name!, _text.text);
      if (!mounted || !a.ok) return;
      setState(() {
        _valid = jBool(a.data['valid']);
        _errors = [for (final e in jList(a.data['errors'])) '$e'];
        _warnings = [for (final e in jList(a.data['warnings'])) '$e'];
      });
    } on Object {
      // offline: Save stays off
    }
  }

  Future<void> _save() async {
    final vpn = AppScope.of(context).vpn;
    final a = _creating
        ? await vpn.act(() => vpn.engine.importConfig(_name.text.trim(), _text.text))
        : await vpn.act(() => vpn.engine.configSave(widget.name!, _text.text));
    if (a != null && a.ok && mounted) {
      vpn.toast(jStr(a.data['note'], 'Saved'), good: true);
      Navigator.pop(context);
    }
  }

  Future<void> _delete() async {
    final vpn = AppScope.of(context).vpn;
    final ok = await confirmDialog(context, question: "Delete ${widget.name}? This can't be undone.", yes: 'Delete', danger: true);
    if (!ok || !mounted) return;
    final a = await vpn.act(() => vpn.engine.configDelete(widget.name!), done: 'Deleted');
    if (a != null && a.ok && mounted) Navigator.pop(context);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _text.dispose();
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return NbDialog(
      width: 720,
      title: _creating ? 'Paste a config' : 'Edit ${widget.name}',
      body: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_creating
              ? 'Paste the contents of a WireGuard .conf file.'
              : 'Private and preshared keys are hidden here and kept exactly as they are unless you replace them.'
                    '${_encrypted ? ' Stored encrypted (Windows DPAPI).' : ''}'),
          const SizedBox(height: NbSpace.x4),
          if (_creating) ...[
            NbTextBox(controller: _name, label: 'Name', hint: 'Home-Mumbai', maxLength: 32),
            const SizedBox(height: NbSpace.x3),
          ],
          NbTextBox(
            controller: _text,
            label: 'Config text',
            lines: 12,
            mono: true,
            onChanged: (_) {
              _debounce?.cancel();
              _debounce = Timer(const Duration(milliseconds: 300), _check);
            },
          ),
          const SizedBox(height: NbSpace.x3),
          Semantics(
            liveRegion: true,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final e in _errors) Text('✕ $e', style: NbType.text(13, c.blocked, height: 1.5)),
                for (final w in _warnings) Text('⚠ $w', style: NbType.text(13, c.amber, height: 1.5)),
                if (_loaded && _errors.isEmpty && _warnings.isEmpty && _valid)
                  Text('✓ Config looks valid', style: NbType.text(13, c.sealed, height: 1.5)),
              ],
            ),
          ),
        ],
      ),
      actions: [
        if (!_creating) NbButton('Delete', kind: NbButtonKind.danger, onPressed: _delete),
        NbButton('Cancel', kind: NbButtonKind.ghost, onPressed: () => Navigator.pop(context)),
        NbButton('Save', onPressed: _valid ? _save : null),
      ],
    );
  }
}
