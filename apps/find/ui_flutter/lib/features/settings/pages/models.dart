/// Models: your PC, meaning search, photo meaning. Every download goes through the consent dialog.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/typography.dart';
import '../../../engine/models/format.dart';
import '../../../engine/models/settings.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/panels.dart';
import '../../consent/download_consent_dialog.dart';
import '../settings_parts.dart';

class ModelsPage extends StatelessWidget {
  const ModelsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SettingsGroup('Your PC', rows: [
        Padding(padding: const EdgeInsets.all(14), child: HardwareTiles(s.settings.hardware)),
      ]),
      const SettingsGroup('Meaning search', rows: [
        SwitchSetting('allow_model_download', 'Allow the one-time model download',
            "23 MB from Hugging Face (all-MiniLM-L6-v2, pinned and checked by SHA-256). This is NOBAD Find's only "
                'internet connection.'),
        SwitchSetting('semantic', 'Search by meaning',
            'Finds “lease agreement” when you type “rent”, and photos or bills by what their names mean. Runs on '
                'this PC only.'),
        _ModelRow('meaning', 'Model'),
      ]),
      const SettingsGroup('Photo meaning', rows: [
        SwitchSetting('allow_photo_model_download', 'Allow the one-time photo model download',
            'About 211 MB from Hugging Face (SigLIP base by Google, Apache-2.0; pinned and checked by SHA-256). '
                'Only needed for this feature.'),
        SwitchSetting('photo_meaning', "Find photos by what's in them",
            '“Dog on a beach” finds IMG_0042.jpg even with no words in it. Runs on this PC only. The first pass '
                'is slow (a few photos per second), in the background.'),
        _ModelRow('photo', 'Photo model'),
      ]),
    ]);
  }
}

class _ModelRow extends StatelessWidget {
  const _ModelRow(this.id, this.label);
  final String id;
  final String label;

  @override
  Widget build(BuildContext context) {
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
          : NbButton('Download', onPressed: () {
              unawaited(s.settings.download(id, consent: () => askDownloadConsent(context, id)));
            }),
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
    final drive = h.ssd == true ? 'SSD' : h.ssd == false ? 'Hard disk' : 'Disk';
    return TileGrid(min: 140, children: [
      StatTile(value: gb(h.ramGb), label: 'Memory'),
      StatTile(value: '${groupDigits(h.cores)} cores', label: '${groupDigits(h.threads)} threads'),
      StatTile(
          value: h.gpu.isEmpty ? 'None found' : h.gpu,
          label: h.gpu.isEmpty
              ? 'Graphics card'
              : '${h.vramGb > 0 ? '${gb(h.vramGb)} video memory' : 'Graphics card'}${h.directml ? ', usable for models' : ''}'),
      StatTile(value: fast.isEmpty ? 'Standard' : fast, label: 'Processor speed-ups'),
      StatTile(value: drive, label: h.diskFreeGb > 0 ? '${gb(h.diskFreeGb)} free' : 'Drive type'),
    ]);
  }
}
