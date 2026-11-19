/// Models & languages: this PC, the tier recommended for it, the language focus, and every model the engine
/// offers, with what it does, what it costs and whether this PC can run it. Use, Download (consent first), Remove,
/// Auto-configure. An engine without the 0.8 model methods gets the older page and says why, never made-up models.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/tokens.dart';
import '../../../app/theme/typography.dart';
import '../../../engine/models/format.dart';
import '../../../engine/models/models_info.dart';
import '../../../engine/models/settings.dart';
import '../../../state/models_controller.dart';
import '../../../widgets/common.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/glass.dart';
import '../../../widgets/panels.dart';
import '../../consent/download_consent_dialog.dart';
import '../settings_parts.dart';

class ModelsPage extends StatefulWidget {
  const ModelsPage({super.key, this.windowsFocus});

  /// Tests: the focus Windows' languages suggest (else read from Windows).
  final String? Function()? windowsFocus;

  @override
  State<ModelsPage> createState() => _ModelsPageState();
}

class _ModelsPageState extends State<ModelsPage> {
  ModelsController? _m;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_m != null) return;
    final s = AppScope.of(context);
    _m = ModelsController(s.engine, toasts: s.toasts, windowsFocus: widget.windowsFocus);
    unawaited(_m!.refresh());
  }

  @override
  void dispose() {
    _m?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: _m!,
    builder: (context, _) {
      final m = _m!;
      return switch (m.load) {
        ModelsLoad.loading => const SizedBox(height: 200),
        ModelsLoad.ready => _Catalogue(m),
        ModelsLoad.needsNewer => _Legacy(note: 'Choosing between models needs a newer engine. ${m.why}'.trim()),
        ModelsLoad.offline => const _Legacy(),
      };
    },
  );
}

Future<bool> _consent(BuildContext context, ModelInfo m) => askModelConsent(context, m);

class _Catalogue extends StatelessWidget {
  const _Catalogue(this.m);
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final info = m.info;
    final focus = info.languageFocus;
    final text = info.byFeature('text');
    // the chosen focus's group first, then the others
    final order = [?focus, ...LanguageFocus.values.where((f) => f != focus)];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _PcAndTier(m),
        if (focus != null)
          SettingsGroup(
            'Languages',
            rows: [
              SettingRow(
                label: 'What your files are in',
                help: '${focus.help}. This changes what is recommended; nothing is downloaded or switched by itself.',
                below: Align(
                  alignment: Alignment.centerLeft,
                  child: NbSegmented<LanguageFocus>(
                    value: focus,
                    badge: m.suggestedFocus,
                    badgeText: 'Matches Windows',
                    options: [for (final f in LanguageFocus.values) (f, f.label)],
                    onChanged: m.busy('focus') ? null : (f) => unawaited(m.setFocus(f)),
                  ),
                ),
              ),
            ],
          ),
        _FeatureGroup(
          title: 'Meaning search',
          switchKey: 'semantic',
          switchLabel: 'Search by meaning',
          switchHelp: 'Finds “lease agreement” when you type “rent”. Runs on this PC only.',
          groups: focus == null
              ? [('', text)]
              : [
                  for (final f in order)
                    if (text.any((x) => x.focus == f))
                      (
                        f.label,
                        [
                          for (final x in text)
                            if (x.focus == f) x,
                        ],
                      ),
                ],
          m: m,
        ),
        _FeatureGroup(
          title: 'Photos by what is in them',
          switchKey: 'photo_meaning',
          switchLabel: "Find photos by what's in them",
          switchHelp: '“Dog on a beach” finds IMG_0042.jpg. The first pass is slow, in the background.',
          groups: [('', info.byFeature('photo'))],
          m: m,
        ),
        _FeatureGroup(
          title: 'Words in pictures',
          switchKey: 'ocr',
          switchLabel: 'Read words in screenshots and scans',
          switchHelp: 'Uses Windows OCR, after everything else is indexed.',
          groups: [('', info.byFeature('ocr'))],
          m: m,
        ),
      ],
    );
  }
}

/// Your PC, the tier recommended for it, the tier in use, and Auto-configure.
class _PcAndTier extends StatelessWidget {
  const _PcAndTier(this.m);
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final info = m.info;
    final rec = info.tierRecommended;
    final now = info.tierCurrent;
    final matches = rec.isNotEmpty && rec == now;
    return SettingsGroup(
      'Your PC',
      rows: [
        Padding(padding: const EdgeInsets.all(12), child: HardwareTiles(info.pc)),
        if (rec.isNotEmpty)
          SettingRow(
            label: 'Recommended for this PC: ${tierLabel(rec)}',
            helpWidget: Text.rich(
              TextSpan(
                children: [
                  TextSpan(text: tierWhy(rec)),
                  if (now.isNotEmpty)
                    TextSpan(
                      text: '  Now: ${tierLabel(now)}.',
                      style: NbType.text(12, matches ? c.orange : c.text, weight: FontWeight.w600),
                    ),
                ],
              ),
              style: NbType.text(12, c.dim, height: 1.4),
            ),
            control: NbButton(
              m.autoBusy ? 'Setting up…' : (matches ? 'Set up again' : 'Auto-configure'),
              small: true,
              kind: matches ? NbButtonKind.ghost : NbButtonKind.primary,
              onPressed: m.autoBusy ? null : () => unawaited(m.autoConfigure(consent: (x) => _consent(context, x))),
            ),
          ),
      ],
    );
  }
}

/// What a tier is for (the engine's table, nobadfind/models.py).
String tierWhy(String tier) => switch (tier) {
  'light' => 'Small, fast models for under 8 GB of memory or few cores.',
  'balanced' => 'Many languages and photos, for 8 to 16 GB of memory and 4+ cores.',
  'best' => 'The most accurate models, for 16 GB+ and 8+ cores or a graphics card that can run them.',
  _ => '',
};

/// One feature: its on/off switch, then its models (text models in language groups).
class _FeatureGroup extends StatelessWidget {
  const _FeatureGroup({
    required this.title,
    required this.switchKey,
    required this.switchLabel,
    required this.switchHelp,
    required this.groups,
    required this.m,
  });
  final String title;
  final String switchKey;
  final String switchLabel;
  final String switchHelp;
  final List<(String, List<ModelInfo>)> groups;
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    if (groups.every((g) => g.$2.isEmpty)) return const SizedBox.shrink();
    return SettingsGroup(
      title,
      rows: [
        SwitchSetting(switchKey, switchLabel, switchHelp),
        for (final (label, models) in groups) ...[
          if (label.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(label.toUpperCase(), style: NbType.data(12, c.dim, weight: FontWeight.w600)),
              ),
            ),
          for (final x in models) _ModelRow(x, m),
        ],
      ],
    );
  }
}

class _ModelRow extends StatelessWidget {
  const _ModelRow(this.x, this.m);
  final ModelInfo x;
  final ModelsController m;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final p = m.progress(x.id);
    final downloading = x.state == ModelUseState.downloading || p != null;
    final facts = [
      if (x.builtin) 'Built into Windows' else if (x.sizeMb > 0) '${x.sizeMb.round()} MB',
      if (x.ramMb > 0) '${x.ramMb.round()} MB RAM',
      if (x.licence.isNotEmpty) x.licence,
      if (x.languages.isNotEmpty) x.languageText,
    ].join('  ·  ');
    final q = x.quality;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 12, 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(x.name, style: NbType.text(13.5, c.text, weight: FontWeight.w600, height: 1.3)),
                    if (x.tier.isNotEmpty) _Tag(tierLabel(x.tier)),
                    if (x.recommended) const _Tag('Recommended', strong: true),
                  ],
                ),
                if (x.improves.isNotEmpty) Text(x.improves, style: NbType.text(12, c.muted, height: 1.45)),
                Text(facts, style: NbType.data(11, c.dim, height: 1.55)),
                if (x.speedNote.isNotEmpty) Text(x.speedNote, style: NbType.text(12, c.dim, height: 1.4)),
                if (q != null)
                  Text(
                    'Measured: ${(q.recall5 * 100).round()}% in the top 5 · ranking ${q.ndcg10.toStringAsFixed(2)} '
                    '(nDCG@10)',
                    style: NbType.data(11, c.muted, height: 1.55),
                  ),
                if (x.source.isNotEmpty)
                  TailText(
                    x.source.replaceFirst(RegExp(r'^https?://'), ''),
                    style: NbType.data(12, c.dim),
                    textAlign: TextAlign.left,
                  ),
                if (!x.capable && x.capableReason.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(x.capableReason, style: NbType.text(12, c.warn, weight: FontWeight.w600, height: 1.4)),
                  ),
                if (x.state == ModelUseState.failed && p == null)
                  Text('The last download failed.', style: NbType.text(12, c.danger, height: 1.4)),
                if (downloading) ...[
                  const SizedBox(height: 6),
                  NbMeter(fraction: p?.fraction ?? 0, busy: p == null || p.sizeMb == 0),
                  const SizedBox(height: 2),
                  Text(
                    p == null || p.sizeMb == 0
                        ? 'Downloading…'
                        : 'Downloading… ${p.gotMb.round()} of ${p.sizeMb.round()} MB'
                              '${p.mbS > 0 ? ' · ${p.mbS.toStringAsFixed(1)} MB/s' : ''}',
                    style: NbType.data(11, c.dim),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 12),
          _Actions(x: x, m: m, busy: m.busy(x.id) || downloading),
        ],
      ),
    );
  }
}

class _Actions extends StatelessWidget {
  const _Actions({required this.x, required this.m, required this.busy});
  final ModelInfo x;
  final ModelsController m;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    if (x.state == ModelUseState.active) {
      return Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text('In use', style: NbType.text(12.5, c.orange, weight: FontWeight.w600)),
      );
    }
    void use() => unawaited(m.use(x, consent: (y) => _consent(context, y)));
    final List<Widget> buttons;
    if (busy) {
      buttons = const [];
    } else if (x.onDisk) {
      buttons = [
        NbButton('Use', small: true, onPressed: use),
        if (!x.builtin)
          NbButton('Remove', small: true, kind: NbButtonKind.quiet, onPressed: () => unawaited(m.remove(x))),
      ];
    } else {
      buttons = [
        NbButton(
          x.capable ? 'Download…' : 'Download anyway…',
          small: true,
          kind: x.capable && x.recommended ? NbButtonKind.primary : NbButtonKind.ghost,
          onPressed: use,
        ),
      ];
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.end, spacing: 6, children: buttons);
  }
}

class _Tag extends StatelessWidget {
  const _Tag(this.text, {this.strong = false});
  final String text;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final color = strong ? c.orange : c.dim;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        color: color.withValues(alpha: strong ? .12 : .06),
        border: Border.all(color: color.withValues(alpha: .35)),
        borderRadius: NbRadius.pillAll,
      ),
      child: Text(text, style: NbType.text(10.5, color, weight: FontWeight.w600, height: 1.3)),
    );
  }
}

/// An engine without the 0.8 model methods (or none yet): the meaning and photo models as before, and why.
class _Legacy extends StatelessWidget {
  const _Legacy({this.note = ''});
  final String note;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (note.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: NbSpace.x4),
            child: Glass(
              radius: 18,
              padding: const EdgeInsets.all(12),
              child: Text(note, style: NbType.text(13, c.muted, height: 1.45)),
            ),
          ),
        SettingsGroup(
          'Your PC',
          rows: [Padding(padding: const EdgeInsets.all(12), child: HardwareTiles(s.settings.hardware))],
        ),
        const SettingsGroup(
          'Meaning search',
          rows: [
            SwitchSetting(
              'allow_model_download',
              'Allow the one-time model download',
              "23 MB from Hugging Face (all-MiniLM-L6-v2, pinned and checked by SHA-256). This is NOBAD Find's only "
                  'internet connection.',
            ),
            SwitchSetting(
              'semantic',
              'Search by meaning',
              'Finds “lease agreement” when you type “rent”, and photos or bills by what their names mean. Runs on '
                  'this PC only.',
            ),
            _LegacyModelRow('meaning', 'Model'),
          ],
        ),
        const SettingsGroup(
          'Photo meaning',
          rows: [
            SwitchSetting(
              'allow_photo_model_download',
              'Allow the one-time photo model download',
              'About 211 MB from Hugging Face (SigLIP base by Google, Apache-2.0; pinned and checked by SHA-256). '
                  'Only needed for this feature.',
            ),
            SwitchSetting(
              'photo_meaning',
              "Find photos by what's in them",
              '“Dog on a beach” finds IMG_0042.jpg even with no words in it. Runs on this PC only. The first pass '
                  'is slow (a few photos per second), in the background.',
            ),
            _LegacyModelRow('photo', 'Photo model'),
          ],
        ),
      ],
    );
  }
}

class _LegacyModelRow extends StatelessWidget {
  const _LegacyModelRow(this.id, this.label);
  final String id;
  final String label;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([AppScope.of(context).status, AppScope.of(context).settings]),
    builder: (context, _) => _build(context),
  );

  Widget _build(BuildContext context) {
    final s = AppScope.of(context);
    final m = s.status.model(id);
    final photos = s.status.details?.photoVectors ?? 0;
    final help = m.ready
        ? (id == 'photo'
              ? 'Downloaded and verified. ${groupDigits(photos)} photos understood so far.'
              : 'Downloaded and verified.')
        : m.downloading
        ? 'Downloading… ${m.percent}%'
        : (m.error.isNotEmpty ? 'Last try failed: ${m.error}' : 'Not downloaded.');
    return SettingRow(
      label: label,
      help: help,
      control: m.ready || m.downloading
          ? null
          : NbButton(
              'Download',
              small: true,
              onPressed: () {
                unawaited(s.settings.download(id, consent: () => askDownloadConsent(context, id)));
              },
            ),
      below: m.downloading ? NbMeter(fraction: m.percent / 100) : null,
    );
  }
}

/// "Your PC": memory, cores, graphics, processor speed-ups, drive (0.7.0 hardwareBlock).
class HardwareTiles extends StatelessWidget {
  const HardwareTiles(this.h, {super.key});
  final Hardware? h;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final h = this.h;
    if (h == null) return Text('Not available here.', style: NbType.text(13, c.dim));
    final fast = [if (h.avx2) 'AVX2', if (h.avx512Vnni) 'AVX-512 VNNI'].join(' + ');
    final drive = h.ssd == true
        ? 'SSD'
        : h.ssd == false
        ? 'Hard disk'
        : 'Disk';
    return TileGrid(
      min: 130,
      children: [
        StatTile(value: gb(h.ramGb), label: 'Memory'),
        StatTile(value: '${groupDigits(h.cores)} cores', label: '${groupDigits(h.threads)} threads'),
        StatTile(
          value: h.gpu.isEmpty ? 'None found' : h.gpu,
          label: h.gpu.isEmpty
              ? 'Graphics card'
              : '${h.vramGb > 0 ? '${gb(h.vramGb)} video memory' : 'Graphics card'}${h.directml ? ', usable for models' : ''}',
        ),
        StatTile(value: fast.isEmpty ? 'Standard' : fast, label: 'Processor speed-ups'),
        StatTile(value: drive, label: h.diskFreeGb > 0 ? '${gb(h.diskFreeGb)} free' : 'Drive type'),
      ],
    );
  }
}
