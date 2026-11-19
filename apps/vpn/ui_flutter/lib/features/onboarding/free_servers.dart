/// "Free servers": the default onboarding. NOBAD has no servers of its own and never ships configs (a shared one
/// would give every user the same private key), so this guides people to their own free account and imports the
/// files they download. While it's open it looks in Downloads every 4 seconds (read-only), so new files appear by
/// themselves. Texts are the WebView guide's (app_ext.js freeServers()).
library;

import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../widgets/controls.dart';
import '../../widgets/dialogs.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';
import '../actions.dart';

Future<void> showFreeServers(BuildContext context) => showScoped<void>(
  context,
  (ctx) => NbDialog(
    width: 760,
    title: 'Free servers',
    body: const FreeServersGuide(),
    actions: [NbButton('Close', kind: NbButtonKind.ghost, onPressed: () => Navigator.pop(ctx))],
  ),
);

class FreeServersGuide extends StatefulWidget {
  const FreeServersGuide({super.key, this.poll = const Duration(seconds: 4)});

  /// How often Downloads is looked at while the guide is open (null: once; tests).
  final Duration? poll;

  @override
  State<FreeServersGuide> createState() => _FreeServersGuideState();
}

class _FreeServersGuideState extends State<FreeServersGuide> {
  List<FreeFile> _files = const [];
  final _sel = <String>{};
  bool _busy = false, _scanned = false;
  String _sig = '';
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _scan());
    if (widget.poll != null) _timer = Timer.periodic(widget.poll!, (_) => _scan());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _scan() async {
    if (!mounted) return;
    try {
      final a = await AppScope.of(context).engine.freeScan();
      if (!mounted || !a.ok) return;
      final files = [for (final f in jList(a.data['files'])) FreeFile.fromJson(f)];
      final sig = files.map((f) => '${f.file}${f.already}').join('|');
      if (sig == _sig && _scanned) return;
      final known = _files.map((f) => f.file).toSet();
      setState(() {
        for (final f in files) {
          if (!f.already && !known.contains(f.file)) _sel.add(f.file); // new downloads start ticked
        }
        _files = files;
        _sig = sig;
        _scanned = true;
      });
    } on Object {
      // offline: the screen says so elsewhere
    }
  }

  Future<void> _add() async {
    final vpn = AppScope.of(context).vpn;
    final files = [for (final f in _files) if (!f.already && _sel.contains(f.file)) f.file];
    if (files.isEmpty) return;
    setState(() => _busy = true);
    final a = await vpn.act(() => vpn.engine.freeImport(files));
    if (!mounted) return;
    setState(() {
      _busy = false;
      _sig = '';
      _sel.clear();
    });
    if (a != null) {
      final imported = [for (final x in jList(a.data['imported'])) '$x'];
      if (imported.isNotEmpty) vpn.toast('Added ${imported.length} server(s): ${imported.join(', ')}', good: true);
      final errs = jList(a.data['errors']);
      if (errs.isNotEmpty && a.ok) vpn.toast('${errs.first}');
    }
    unawaited(_scan());
  }

  Future<void> _link(String key) async {
    final vpn = AppScope.of(context).vpn;
    await vpn.act(() => vpn.engine.openUrl(key), done: 'Opening in your browser…');
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final fresh = _files.where((f) => !f.already).toList();
    Widget group({required String title, String? chip, required List<Widget> children}) => Container(
      margin: const EdgeInsets.only(bottom: NbSpace.x3),
      padding: const EdgeInsets.all(NbSpace.x4),
      decoration: BoxDecoration(color: c.card, borderRadius: NbRadius.rowAll, border: Border.all(color: c.line)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Flexible(child: Text(title, style: NbType.text(NbSize.title, c.text, weight: FontWeight.w600))),
              if (chip != null) ...[
                const SizedBox(width: NbSpace.x2),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
                  decoration: BoxDecoration(borderRadius: NbRadius.pillAll, border: Border.all(color: c.line2)),
                  child: Text(chip, style: NbType.text(NbSize.caption, c.muted)),
                ),
              ],
            ],
          ),
          const SizedBox(height: NbSpace.x2),
          ...children,
        ],
      ),
    );
    Widget step(int n, String text, [Widget? action]) => Padding(
      padding: const EdgeInsets.only(top: NbSpace.x2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 22,
            height: 22,
            alignment: Alignment.center,
            decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: c.orangeA(.6))),
            child: Text('$n', style: NbType.data(12, c.orange)),
          ),
          const SizedBox(width: NbSpace.x3),
          Expanded(
            child: Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: NbSpace.x3,
              runSpacing: NbSpace.x2,
              children: [Text(text, style: NbType.text(14, c.text, height: 1.5)), ?action],
            ),
          ),
        ],
      ),
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('NOBAD connects with WireGuard configs from any provider. These are free and safe ways to get some.'),
        const SizedBox(height: NbSpace.x4),
        group(
          title: 'Proton VPN Free',
          chip: 'several countries',
          children: [
            Text(
              'No-logs VPN with free servers in a few countries (for example the Netherlands, Japan, the United States, '
              'Poland and Romania). Each config is made for your own free account.',
              style: NbType.text(13, c.muted, height: 1.5),
            ),
            step(1, 'Create a free Proton account (or sign in).',
                NbButton('Create free account', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.external,
                    onPressed: () => _link('proton_signup'))),
            step(2, 'Open Downloads → WireGuard configuration, choose Windows and a free server, and download the file. '
                    'Repeat for each country you want.',
                NbButton('Open WireGuard downloads', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.external,
                    onPressed: () => _link('proton_downloads'))),
            step(3, 'Come back here: NOBAD finds the files in your Downloads folder by itself.'),
            const SizedBox(height: NbSpace.x3),
            _found(c, fresh),
          ],
        ),
        group(
          title: 'Cloudflare WARP',
          chip: 'nearest location',
          children: [
            Text(
              'Free, but Cloudflare only gives WARP connections to its own app, and always picks the nearest location. '
              'Use the official 1.1.1.1 app for WARP; NOBAD is for the configs above and your own servers.',
              style: NbType.text(13, c.muted, height: 1.5),
            ),
            const SizedBox(height: NbSpace.x2),
            NbButton('Get the 1.1.1.1 app', small: true, kind: NbButtonKind.ghost, icon: NbGlyph.external,
                onPressed: () => _link('warp_app')),
          ],
        ),
        group(
          title: 'Your own server or provider',
          children: [
            Text('Any WireGuard .conf works: from a paid provider, a router, or a server you run. Import it, paste it, '
                'or scan its QR code.', style: NbType.text(13, c.muted, height: 1.5)),
          ],
        ),
        Text(
          'Never use configs copied from "free config" websites: everyone using them shares the same private key, and '
          "you can't know who runs the server.",
          style: NbType.text(13, c.muted, height: 1.5),
        ),
      ],
    );
  }

  Widget _found(NbColors c, List<FreeFile> fresh) {
    if (!_scanned) {
      return Text('Looking in your Downloads folder…', style: NbType.text(13, c.muted));
    }
    if (_files.isEmpty) {
      return Wrap(
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: NbSpace.x3,
        children: [
          Text('No WireGuard files downloaded in the last two weeks yet. This list updates by itself.',
              style: NbType.text(13, c.muted, height: 1.5)),
          NbButton('Pick files instead', small: true, kind: NbButtonKind.quiet, onPressed: () => importFiles(context)),
        ],
      );
    }
    return Semantics(
      liveRegion: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text('Found in Downloads', style: NbType.text(14, c.text, weight: FontWeight.w600)),
              const SizedBox(width: NbSpace.x2),
              Text('${fresh.length} new', style: NbType.text(13, c.muted)),
            ],
          ),
          const SizedBox(height: NbSpace.x2),
          for (final f in _files) _fileRow(c, f),
          const SizedBox(height: NbSpace.x3),
          Wrap(
            spacing: NbSpace.x2,
            children: [
              NbButton(_busy ? 'Adding…' : 'Add selected servers',
                  onPressed: _busy || !fresh.any((f) => _sel.contains(f.file)) ? null : _add),
              NbButton('Pick other files', kind: NbButtonKind.ghost, onPressed: () => importFiles(context)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _fileRow(NbColors c, FreeFile f) {
    final on = _sel.contains(f.file);
    final sub = [f.name, '${f.host}${f.port.isNotEmpty ? ':${f.port}' : ''}', if (f.provider.isNotEmpty) f.provider]
        .join('  ·  ');
    return Pressable(
      onTap: f.already ? null : () => setState(() => on ? _sel.remove(f.file) : _sel.add(f.file)),
      selected: on,
      semanticLabel: '${f.country.isEmpty ? f.name : f.country}, ${f.already ? 'added' : 'new'}',
      builder: (context, s) => AnimatedOpacity(
        opacity: f.already ? .55 : 1,
        duration: NbMotion.of(context, NbMotion.fast),
        child: Container(
          margin: const EdgeInsets.only(bottom: 6),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            color: s.lit ? c.cardHover : c.raised,
            borderRadius: NbRadius.controlAll,
            border: Border.all(color: on ? c.orangeA(.6) : c.line),
          ),
          child: Row(
            children: [
              Container(
                width: 18,
                height: 18,
                decoration: BoxDecoration(
                  color: on || f.already ? c.orange : null,
                  borderRadius: const BorderRadius.all(Radius.circular(5)),
                  border: Border.all(color: on || f.already ? c.orange : c.line2),
                ),
                child: on || f.already ? NbIcon(NbGlyph.check, size: 16, color: c.onOrange, stroke: 2.2) : null,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(f.country.isEmpty ? f.name : f.country, style: NbType.text(14, c.text, weight: FontWeight.w600)),
                    Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.data(12, c.muted, height: 1.5)),
                  ],
                ),
              ),
              Text(f.already ? 'added' : 'new', style: NbType.text(12, f.already ? c.dim : c.orange)),
            ],
          ),
        ),
      ),
    );
  }
}
