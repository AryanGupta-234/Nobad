/// Index: what NOBAD Find is doing, what it costs, and why. The level and its reason (the page's one loud
/// element), the pipeline with times to go, its own processor/memory/disk/graphics use per process with the last
/// five minutes, the models, recent decisions, the index at a glance, folders, drives and the encryption note.
///
/// Subscribes to `status_full` while open (StatusController.watch) and drops it when closed. No timers.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/format.dart';
import '../../engine/models/status.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';
import '../../widgets/motion.dart';
import '../../widgets/panels.dart';
import '../../widgets/resources_chart.dart';
import '../consent/download_consent_dialog.dart';

class IndexingScreen extends StatefulWidget {
  const IndexingScreen({super.key});

  @override
  State<IndexingScreen> createState() => _IndexingScreenState();
}

class _IndexingScreenState extends State<IndexingScreen> {
  AppScope? _s;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (_s != null) return; // once: the scope is rebuilt with the app, its controllers stay the same
    _s = s;
    unawaited(s.status.watch(true));
  }

  @override
  void dispose() {
    unawaited(_s?.status.watch(false));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: Listenable.merge([s.status, s.settings]),
      builder: (context, _) {
        final st = s.status.status;
        final d = s.status.details;
        return LayoutBuilder(
          builder: (context, box) {
            final wide = box.maxWidth >= NbSpace.wide;
            final body = SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, NbSpace.x6),
              child: Align(
                alignment: Alignment.topLeft,
                child: ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: wide ? NbSpace.maxContent : NbSpace.column),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (!s.settings.settings.flag('bg_notice_seen')) ...[
                        NoticeBar(
                          text:
                              'Closing the window now stops indexing. Turn on Keep indexing in the background in '
                              'Settings → Performance to keep it going.',
                          action: 'Got it',
                          onAction: () => s.settings.set('bg_notice_seen', true),
                        ),
                        const SizedBox(height: NbSpace.x4),
                      ],
                      _Now(status: st, connected: s.status.connected),
                      if (s.status.turbo != null && s.status.connected)
                        Padding(
                          padding: const EdgeInsets.only(top: 8, left: 2),
                          child: Text(
                            s.status.turbo!.line,
                            style: NbType.data(11.5, s.status.turbo!.running ? c.orange : c.dim),
                          ),
                        ),
                      if (!s.status.connected)
                        Padding(
                          padding: const EdgeInsets.only(top: NbSpace.x4),
                          child: Text(s.status.line, style: NbType.text(13, c.warn)),
                        ),
                      // no engine: no numbers at all (old ones would look current)
                      if (d != null && s.status.connected) ..._layout(_details(context, s, d), wide),
                      if (d == null && s.status.connected) const _Loading(),
                    ],
                  ),
                ),
              ),
            );
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                PageHeader(
                  'Index',
                  crumb: 'Status',
                  trailing: s.status.connected
                      ? NbButton('Rescan now', kind: NbButtonKind.ghost, small: true, onPressed: s.settings.rescan)
                      : null,
                ),
                Expanded(child: body),
              ],
            );
          },
        );
      },
    );
  }

  /// Narrow: one column. Wide: a dashboard, what it is doing, the models and the index on the left; what it
  /// uses, recent decisions, folders and drives on the right.
  List<Widget> _layout(List<Widget> flat, bool wide) {
    if (!wide) return flat;
    final sections = <List<Widget>>[];
    for (final w in flat) {
      if (w is SectionTitle || sections.isEmpty) sections.add([]);
      sections.last.add(w);
    }
    // what it is doing spans the width (its rows need room); the rest in two columns
    final first = sections.isEmpty ? <Widget>[] : sections.removeAt(0);
    final left = <Widget>[], right = <Widget>[];
    for (var i = 0; i < sections.length; i++) {
      (i.isEven ? left : right).addAll(sections[i]);
    }
    return [
      ...first,
      Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: left),
          ),
          const SizedBox(width: 28),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: right),
          ),
        ],
      ),
    ];
  }

  List<Widget> _details(BuildContext context, AppScope s, IndexDetails d) {
    final c = NbColors.of(context);
    final r = d.resources;
    final phaseLabel = s.status.status?.phaseLabel ?? '';
    return [
      const SectionTitle('What it is doing', top: NbSpace.x4),
      NbPanel(
        padding: EdgeInsets.zero,
        clip: true,
        child: Column(
          children: [
            for (var i = 0; i < d.phases.length; i++) ...[
              if (i > 0) Container(height: 1, color: c.line),
              _PhaseRowView(d.phases[i]),
            ],
          ],
        ),
      ),
      const SectionTitle('What NOBAD Find uses'),
      TileGrid(
        min: 150,
        children: [
          StatTile(value: pct(r.cpu), label: 'Processor'),
          StatTile(value: r.memoryMb != null ? mb(r.memoryMb) : '–', label: 'Memory'),
          StatTile(
            value: r.readMbS != null ? '${r.readMbS!.toStringAsFixed(r.readMbS! < 10 ? 1 : 0)} MB/s' : '–',
            label: 'Disk reading',
          ),
          StatTile(value: r.gpu == null ? 'Not used' : pct(r.gpu), label: 'Graphics card'),
        ],
      ),
      const SizedBox(height: 10),
      NbPanel(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
        child: ResourcesChart(history: d.history),
      ),
      if (r.processes.isNotEmpty) ...[const SizedBox(height: 10), _ProcessTable(r.processes)],
      const SectionTitle('Models'),
      TileGrid(min: 250, children: [for (final m in d.models) _ModelCardView(m)]),
      const SectionTitle('Recent decisions'),
      _Activity(s.status.activity),
      const SectionTitle('Index at a glance'),
      TileGrid(
        min: 170,
        children: [
          StatTile(value: phaseLabel, label: 'Status', live: s.status.status?.phase != 'watching'),
          StatTile(value: groupDigits(s.status.status?.files ?? 0), label: 'Files and folders'),
          StatTile(value: groupDigits(d.withText), label: 'Files with readable text'),
          StatTile(value: groupDigits(d.vectors + d.nameVectors), label: 'Meaning vectors (text + names)'),
          StatTile(value: groupDigits(d.photoVectors), label: 'Photos understood'),
          StatTile(
            value: d.memoryMb != null ? '${d.memoryMb!.round()} MB' : '–',
            label: d.modelsLoaded.isNotEmpty
                ? 'Memory now · models in use: ${d.modelsLoaded.join(', ')}'
                : 'Memory now · no models loaded (they load when you search)',
          ),
          StatTile(value: d.rate > 0 ? '${groupDigits(d.rate.round())}/s' : '–', label: 'Scan speed'),
          StatTile(value: '${(d.dbBytes / 1048576).toStringAsFixed(0)} MB', label: 'Index size'),
          StatTile(
            value: d.plan != null && d.plan!.cpu > 0
                ? '${d.plan!.textWorkers}–${d.plan!.textWorkersIdle} of ${d.plan!.cpu}'
                : '–',
            label: 'Text workers / CPU threads',
          ),
          StatTile(value: d.speed.isNotEmpty ? d.speedLabel : '–', label: d.speedHelp),
          StatTile(
            value: d.ocrOn ? 'On' : 'Off',
            label: d.ocrOn ? 'OCR (Windows, offline)' : 'OCR: ${d.ocrWhy.isNotEmpty ? d.ocrWhy : 'not available'}',
          ),
          StatTile(value: d.plan?.ssd == null ? '–' : (d.plan!.ssd! ? 'SSD' : 'Hard disk'), label: 'Drive type'),
        ],
      ),
      const SectionTitle('Folders being searched'),
      _PlainList([for (final r in d.roots) (r, '')]),
      const SectionTitle('Drives'),
      _PlainList([
        for (final dr in d.drives)
          ('${dr.root} ${dr.label}'.trim(), '${dr.typeLabel}${dr.present ? '' : ' · not connected'}'),
      ]),
      const SizedBox(height: NbSpace.x5),
      _Encryption(encrypted: d.encrypted),
    ];
  }
}

/// The level, its reason, and Pause / Resume: the page's one loud element.
class _Now extends StatelessWidget {
  const _Now({required this.status, required this.connected});
  final EngineStatus? status;
  final bool connected;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final st = status ?? const EngineStatus();
    final lv = connected ? st.levelKey : 'paused';
    final paused = lv == 'paused';
    final label = connected ? EngineStatus.levelLabels[lv]! : 'Not connected';
    return NbPanel(
      live: lv == 'full',
      padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
      child: Row(
        children: [
          LevelGlyph(level: lv, color: c.orange, dim: c.dim, size: 14),
          const SizedBox(width: 14),
          Expanded(
            child: Semantics(
              liveRegion: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: NbType.text(15, paused ? c.muted : c.text, weight: FontWeight.w700, height: 1.3)),
                  if (st.reason.isNotEmpty && connected) ...[
                    const SizedBox(height: 2),
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 600),
                      child: Text(st.reason, style: NbType.text(12.5, c.muted, height: 1.4)),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(width: 16),
          if (connected)
            NbButton(
              paused ? 'Resume' : 'Pause for 1 hour',
              kind: paused ? NbButtonKind.primary : NbButtonKind.ghost,
              icon: paused ? NbGlyph.play : NbGlyph.pause,
              onPressed: () => paused ? s.engine.resume() : s.engine.pauseFor(const Duration(hours: 1)),
            ),
        ],
      ),
    );
  }
}

class _PhaseRowView extends StatelessWidget {
  const _PhaseRowView(this.p);
  final PhaseRow p;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final off = p.state == PhaseState.off;
    final run = p.state == PhaseState.running;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
      child: Row(
        children: [
          Expanded(
            flex: 14,
            child: Text(
              p.label,
              style: NbType.text(13.5, off ? c.dim : c.text, weight: off ? FontWeight.w400 : FontWeight.w600),
            ),
          ),
          SizedBox(
            width: 84,
            child: Row(
              children: [
                if (p.state == PhaseState.done) ...[
                  NbIcon(NbGlyph.check, size: 13, color: c.orange),
                  const SizedBox(width: 3),
                ],
                Flexible(
                  child: Text(
                    p.stateLabel,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: NbType.text(
                      NbSize.small,
                      run ? c.orange : c.dim,
                      weight: run ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            flex: 20,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                NbMeter(fraction: p.fraction, busy: p.busy, muted: p.state == PhaseState.waiting || off),
                if (p.extra.isNotEmpty) ...[
                  const SizedBox(height: 5),
                  Text(p.extra, textAlign: TextAlign.right, style: NbType.text(NbSize.small - .5, c.dim)),
                ],
              ],
            ),
          ),
          SizedBox(
            width: 140,
            child: Text(p.count, textAlign: TextAlign.right, style: NbType.data(NbSize.caption, off ? c.dim : c.muted)),
          ),
        ],
      ),
    );
  }
}

class _ProcessTable extends StatelessWidget {
  const _ProcessTable(this.rows);
  final List<ProcessUse> rows;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    Widget cell(String t, {bool head = false, bool right = true, int flex = 2}) => Expanded(
      flex: flex,
      child: Text(
        t,
        textAlign: right ? TextAlign.right : TextAlign.left,
        style: head ? NbType.text(NbSize.small, c.dim) : NbType.data(NbSize.caption + .5, c.muted),
      ),
    );
    return NbPanel(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              children: [
                cell('Process', head: true, right: false, flex: 4),
                cell('PID', head: true),
                cell('Processor', head: true),
                cell('Memory', head: true),
              ],
            ),
          ),
          Container(height: 1, color: c.line2),
          for (final p in rows)
            Container(
              padding: const EdgeInsets.symmetric(vertical: 6),
              decoration: BoxDecoration(
                border: Border(bottom: BorderSide(color: c.line)),
              ),
              child: Row(
                children: [
                  Expanded(flex: 4, child: Text(p.name, style: NbType.text(13, c.text))),
                  cell('${p.pid}'),
                  cell(pct(p.cpu)),
                  cell(mb(p.memoryMb)),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _ModelCardView extends StatelessWidget {
  const _ModelCardView(this.m);
  final ModelCard m;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    // A download event is newer than the card in the last status_full.
    final live = m.id == 'ocr' ? null : s.status.model(m.id);
    final downloading = live?.downloading ?? m.download != null;
    final state = live != null && live.downloading
        ? 'Downloading ${mb(live.got / 1048576)} of ${mb(live.size / 1048576)}'
              '${live.mbS > 0 ? ' at ${live.mbS.toStringAsFixed(1)} MB/s' : ''}'
        : m.stateLine;
    final canGet = m.id != 'ocr' && !m.onDisk && !downloading && !(live?.ready ?? false);
    return NbPanel(
      live: m.loaded,
      padding: const EdgeInsets.fromLTRB(15, 13, 15, 13),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(m.name, style: NbType.text(14, c.text, weight: FontWeight.w600)),
          const SizedBox(height: 2),
          Text(state, style: NbType.text(NbSize.small, m.loaded || downloading ? c.orange : c.muted)),
          const SizedBox(height: 8),
          Text(m.facts, style: NbType.data(NbSize.micro + .5, c.dim, height: 1.6)),
          if (downloading && live != null) ...[
            const SizedBox(height: 10),
            NbMeter(fraction: live.size > 0 ? live.got / live.size : (m.download?.fraction ?? 0)),
          ],
          if (canGet) ...[
            const SizedBox(height: 10),
            NbButton(
              'Download…',
              kind: NbButtonKind.ghost,
              small: true,
              onPressed: () {
                unawaited(s.settings.download(m.id, consent: () => askDownloadConsent(context, m.id)));
              },
            ),
          ],
        ],
      ),
    );
  }
}

class _Activity extends StatelessWidget {
  const _Activity(this.items);
  final List<ActivityEntry> items;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return NbPanel(
      padding: EdgeInsets.zero,
      child: items.isEmpty
          ? Padding(
              padding: const EdgeInsets.all(14),
              child: Text(
                'Nothing yet. NOBAD Find adds a line here whenever it changes pace, pauses or finishes something.',
                style: NbType.text(13, c.dim),
              ),
            )
          : Column(
              children: [
                for (var i = 0; i < items.length && i < 12; i++)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    decoration: BoxDecoration(
                      border: i == 0 ? null : Border(top: BorderSide(color: c.line)),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 64,
                          child: Text(clock(items[i].t), style: NbType.data(NbSize.caption, c.dim, height: 1.6)),
                        ),
                        Expanded(child: Text(items[i].text, style: NbType.text(13, c.muted, height: 1.5))),
                      ],
                    ),
                  ),
              ],
            ),
    );
  }
}

class _PlainList extends StatelessWidget {
  const _PlainList(this.rows);
  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    if (rows.isEmpty) return Text('–', style: NbType.data(12, c.dim));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final (a, b) in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(text: a, style: NbType.data(12.5, c.muted)),
                  if (b.isNotEmpty) TextSpan(text: '   $b', style: NbType.text(NbSize.small, c.dim)),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _Encryption extends StatelessWidget {
  const _Encryption({required this.encrypted});
  final bool encrypted;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Text(
      encrypted
          ? 'The index is encrypted on disk (SQLCipher). Its key is protected by your Windows sign-in, and nothing '
                'leaves this PC.'
          : "The index is NOT encrypted: SQLCipher isn't installed in this build. It stays in your own profile folder.",
      style: NbType.text(13, encrypted ? c.muted : c.warn, height: 1.5),
    );
  }
}

/// While the first full status is on its way: the page's shape, quietly.
class _Loading extends StatelessWidget {
  const _Loading();

  @override
  Widget build(BuildContext context) => const Padding(
    padding: EdgeInsets.only(top: NbSpace.x8),
    child: Shimmer(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Skeleton(width: 160, height: 14),
          SizedBox(height: NbSpace.x3),
          Skeleton(height: 230, radius: NbRadius.panel),
          SizedBox(height: NbSpace.x8),
          Skeleton(width: 190, height: 14),
          SizedBox(height: NbSpace.x3),
          Skeleton(height: 150, radius: NbRadius.panel),
        ],
      ),
    ),
  );
}
