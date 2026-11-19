/// What to index: the scope (Whole PC, My files, Custom), every category of place with what it is, example paths,
/// how many files of it are in the index and its switch (nothing is skipped silently), how files are read, and
/// the optional turbo index. An engine without `scope_info` keeps the older folder rows and says why.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/typography.dart';
import '../../../engine/engine_api.dart';
import '../../../engine/events.dart';
import '../../../engine/models/format.dart';
import '../../../engine/models/scope_info.dart';
import '../../../state/settings_controller.dart' show errorText;
import '../../../widgets/controls.dart';
import '../settings_parts.dart';

class IndexingPage extends StatefulWidget {
  const IndexingPage({super.key});

  @override
  State<IndexingPage> createState() => _IndexingPageState();
}

enum _Load { loading, ready, needsNewer, offline }

class _IndexingPageState extends State<IndexingPage> {
  AppScope? _s;
  StreamSubscription<EngineEvent>? _sub;
  _Load _load = _Load.loading;
  String _why = '';
  ScopeInfo _scope = const ScopeInfo();
  TurboState? _turbo;
  bool _turboBusy = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_s != null) return;
    _s = AppScope.of(context);
    _sub = _s!.engine.events.listen((e) {
      if (e is TurboEvent && mounted) setState(() => _turbo = e.state);
    });
    unawaited(_refresh());
  }

  @override
  void dispose() {
    unawaited(_sub?.cancel());
    super.dispose();
  }

  Future<void> _refresh() async {
    final e = _s!.engine;
    try {
      final scope = await e.scopeInfo();
      TurboState? turbo;
      try {
        turbo = await e.turboState();
      } on RpcException {
        turbo = null;
      }
      if (!mounted) return;
      setState(() {
        _scope = scope;
        _turbo = turbo;
        _load = _Load.ready;
      });
    } on RpcException catch (x) {
      if (!mounted) return;
      setState(() {
        _load = x.code == -32601 ? _Load.needsNewer : _Load.offline;
        _why = x.message;
      });
    } on Object {
      if (mounted) setState(() => _load = _Load.offline);
    }
  }

  /// A scope or category switch: the engine walks again, and the list is read again.
  Future<void> _set(String key, Object value) async {
    await _s!.settings.set(key, value);
    await _refresh();
  }

  Future<void> _setTurbo(bool on) async {
    if (_turboBusy) return;
    setState(() => _turboBusy = true);
    try {
      final r = await _s!.engine.turboSet(on);
      if (!r.ok) _s!.toasts.show(r.error.isNotEmpty ? r.error : 'The turbo index stayed off.');
      if (mounted && r.state != null) setState(() => _turbo = r.state);
    } on Object catch (e) {
      _s!.toasts.show(errorText(e));
    }
    if (mounted) setState(() => _turboBusy = false);
  }

  @override
  Widget build(BuildContext context) {
    return switch (_load) {
      _Load.loading => const SizedBox(height: 200),
      _Load.ready => _ready(context),
      _Load.needsNewer => _Older(note: 'Choosing what to index needs a newer engine. $_why'.trim()),
      _Load.offline => const _Older(),
    };
  }

  Widget _ready(BuildContext context) {
    final c = NbColors.of(context);
    final scope = _scope.scope;
    final roots = _scope.roots;
    final turbo = _turbo;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SettingsGroup(
          'Where',
          rows: [
            SettingRow(
              label: 'What to index',
              help: switch (scope) {
                IndexScope.wholePc =>
                  'Every fixed drive. Windows, programs and app data stay out unless you add them below.',
                IndexScope.myFiles => 'Your profile folder: Documents, Desktop, Downloads, Pictures and the rest.',
                IndexScope.custom => 'Only the folders you choose.',
                null => '',
              },
              below: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  NbSegmented<IndexScope>(
                    value: scope,
                    options: [for (final x in IndexScope.values) (x, x.label)],
                    onChanged: (x) => unawaited(_set('scope', x.wire)),
                  ),
                  if (scope != IndexScope.custom && roots.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(roots.join('   '), style: NbType.data(11.5, c.dim)),
                  ],
                ],
              ),
            ),
            if (scope == IndexScope.custom)
              const FoldersSetting('roots', 'Folders', 'NOBAD Find indexes these folders and what is inside them.'),
            const FoldersSetting(
              'exclude',
              'Never index',
              'These folders and files are skipped and removed from the index.',
            ),
          ],
        ),
        SettingsGroup(
          'What is included',
          rows: [for (final k in _scope.categories) _CategoryRow(k, onSet: (on) => _set(k.setting, on))],
        ),
        const SettingsGroup(
          'Reading files',
          rows: [
            SwitchSetting(
              'content',
              'Read the text inside files',
              'Documents, PDFs, code, notes and e-mail files. Off: names only.',
            ),
            TextSetting(
              'content_max_mb',
              'Largest file to read (MB)',
              'Bigger files are still found by name.',
              number: true,
            ),
            SwitchSetting(
              'ocr',
              'Words in photos and scans',
              'Read with the OCR built into Windows (offline). Slower, so it runs after everything else.',
            ),
            SwitchSetting('src_mail', 'E-mail files', '.eml and .mbox files found on your drives.'),
          ],
        ),
        if (turbo != null)
          SettingsGroup(
            'Turbo index (needs administrator once per session)',
            rows: [
              SettingRow(
                label: 'Turbo index',
                help:
                    "Reads NTFS's own list of files and its change journal: file names, sizes and dates, so a whole "
                    'drive is listed in seconds and changes show up at once. Never file contents, and never other '
                    "people's files. Windows asks for administrator permission (UAC) once each time NOBAD Find starts.",
                control: _turboBusy
                    ? Text('Waiting for Windows…', style: NbType.text(12, c.dim))
                    : NbSwitch(
                        value: turbo.enabled || turbo.running,
                        label: 'Turbo index',
                        onChanged: turbo.available ? (v) => unawaited(_setTurbo(v)) : null,
                      ),
                below: _TurboTable(turbo),
              ),
            ],
          ),
      ],
    );
  }
}

class _CategoryRow extends StatelessWidget {
  const _CategoryRow(this.k, {required this.onSet});
  final ScopeCategory k;
  final ValueChanged<bool> onSet;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final canSwitch = !k.locked && k.setting.isNotEmpty;
    final count = k.count == null ? 'not counted' : '${groupDigits(k.count!)} in the index';
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 9, 12, 9),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(k.name, style: NbType.text(13.5, c.text, weight: FontWeight.w600, height: 1.35)),
                    ),
                    const SizedBox(width: 8),
                    Text(count, style: NbType.data(11, k.included ? c.muted : c.dim)),
                  ],
                ),
                if (k.why.isNotEmpty) Text(k.why, style: NbType.text(12, c.dim, height: 1.4)),
                if (k.examples.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(k.examples.join('   '), style: NbType.data(11, c.dim, height: 1.5)),
                  ),
                if (k.id == 'secrets' && (k.included || canSwitch))
                  Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Text(
                      'Names only: the contents of these files are never read.',
                      style: NbType.text(12, c.warn, weight: FontWeight.w600, height: 1.4),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          if (canSwitch)
            NbSwitch(value: k.included, label: k.name, onChanged: onSet)
          else
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(k.included ? 'Always in' : 'Always out', style: NbType.text(12, c.dim)),
            ),
        ],
      ),
    );
  }
}

/// Per drive: NTFS or not, files read, whether changes come from the change journal, when it was read.
class _TurboTable extends StatelessWidget {
  const _TurboTable(this.t);
  final TurboState t;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget cell(String s, {bool head = false, double w = 90}) => SizedBox(
      width: w,
      child: Text(s, style: head ? NbType.text(11, c.dim, weight: FontWeight.w600) : NbType.data(11.5, c.muted)),
    );
    String when(double? t) {
      if (t == null) return '—';
      final d = DateTime.now().difference(DateTime.fromMillisecondsSinceEpoch((t * 1000).round()));
      return d.inSeconds < 60 ? 'just now' : '${span(d.inSeconds)} ago';
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(t.line, style: NbType.text(12, t.running ? c.orange : c.muted, weight: FontWeight.w600)),
        if (t.volumes.isNotEmpty) ...[
          const SizedBox(height: 6),
          Row(
            children: [
              cell('Drive', head: true, w: 60),
              cell('File system', head: true),
              cell('Files', head: true),
              cell('Changes', head: true, w: 120),
              cell('Read', head: true),
            ],
          ),
          for (final v in t.volumes)
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Row(
                children: [
                  cell(v.label, w: 60),
                  cell(v.ntfs ? 'NTFS' : 'Not NTFS'),
                  cell(v.files > 0 ? groupDigits(v.files) : '—'),
                  cell(v.usnOk ? 'Change journal' : (v.ntfs ? 'Folder walk' : '—'), w: 120),
                  cell(when(v.lastScan)),
                ],
              ),
            ),
        ],
      ],
    );
  }
}

/// The 0.7.0 rows, for an engine without `scope_info`.
class _Older extends StatelessWidget {
  const _Older({this.note = ''});
  final String note;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (note.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Text(note, style: NbType.text(13, c.muted, height: 1.45)),
          ),
        const SettingsGroup(
          'What to search',
          rows: [
            FoldersSetting(
              'roots',
              'Folders to search',
              "Empty: your profile folder and every fixed drive (never other people's profiles or Windows itself).",
            ),
            FoldersSetting(
              'exclude',
              'Never search',
              'These folders and files are skipped and removed from the index.',
            ),
            SwitchSetting(
              'content',
              'Read the text inside files',
              'Documents, PDFs, code, notes and e-mail files. Off: names only.',
            ),
            TextSetting(
              'content_max_mb',
              'Largest file to read (MB)',
              'Bigger files are still found by name.',
              number: true,
            ),
            SwitchSetting(
              'ocr',
              'Words in photos and scans',
              'Screenshots, photos of documents and scanned PDFs, read with the OCR built into Windows (offline). '
                  'Slower, so it runs after everything else.',
            ),
            SwitchSetting('src_mail', 'E-mail files', '.eml and .mbox files found on your drives.'),
            SwitchSetting(
              'index_removable',
              'USB and external drives',
              'Indexed while plugged in. Their files stay findable (marked “not connected”) when you unplug them. '
                  'Turning this off removes their files from the index.',
            ),
            SwitchSetting(
              'index_network',
              'Network drives',
              'Mapped network drives (Z: and so on). Big shares take a while and use your home or office network.',
            ),
          ],
        ),
      ],
    );
  }
}
