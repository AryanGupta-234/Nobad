/// Consent before a model download: what it is, how big, from where, under which licence, how it's checked, and
/// that it's NOBAD Find's only internet connection. Nothing downloads without "Download" here.
library;

import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models/models_info.dart';
import '../../widgets/controls.dart';
import '../../widgets/dialogs.dart';

class ModelOffer {
  const ModelOffer({
    required this.id,
    required this.title,
    required this.what,
    required this.facts,
    required this.source,
  });
  final String id;
  final String title;
  final String what;

  /// (label, value) rows.
  final List<(String, String)> facts;

  /// The 0.7.0 sentence about the download (Settings → Models).
  final String source;

  static const meaning = ModelOffer(
    id: 'meaning',
    title: 'Download the meaning model?',
    what:
        'Finds “lease agreement” when you type “rent”, and photos or bills by what their names mean. '
        'Runs on this PC only.',
    facts: [
      ('Model', 'all-MiniLM-L6-v2'),
      ('Size', '23 MB, once'),
      ('From', 'Hugging Face'),
      ('Licence', 'Apache-2.0'),
      ('Checked', 'Pinned revision, SHA-256'),
    ],
    source:
        '23 MB from Hugging Face (all-MiniLM-L6-v2, pinned and checked by SHA-256). '
        "This is NOBAD Find's only internet connection.",
  );

  static const photo = ModelOffer(
    id: 'photo',
    title: 'Download the photo model?',
    what:
        '“Dog on a beach” finds IMG_0042.jpg even with no words in it. Runs on this PC only. The first pass is '
        'slow (a few photos per second), in the background.',
    facts: [
      ('Model', 'SigLIP base by Google'),
      ('Size', 'About 211 MB, once'),
      ('From', 'Hugging Face'),
      ('Licence', 'Apache-2.0'),
      ('Checked', 'Pinned revision, SHA-256'),
    ],
    source:
        'About 211 MB from Hugging Face (SigLIP base by Google, Apache-2.0; pinned and checked by SHA-256). '
        'Only needed for this feature.',
  );

  static ModelOffer of(String id) => id == 'photo' ? photo : meaning;

  /// A model from the engine's catalogue (0.8 `models`): what it improves, size, source, licence, memory.
  factory ModelOffer.model(ModelInfo m) {
    final size = m.sizeMb > 0 ? '${m.sizeMb.round()} MB, once' : 'Nothing to download';
    return ModelOffer(
      id: m.id,
      title: 'Download ${m.name}?',
      what: [
        m.improves.isNotEmpty ? m.improves : featureLabel(m.feature),
        'Runs on this PC only.',
        if (m.feature == 'text')
          'Your files are read again for it in the background; the current model works until then.',
      ].join(' '),
      facts: [
        ('Model', m.name),
        ('Improves', featureLabel(m.feature)),
        ('Size', size),
        ('From', m.source),
        ('Licence', m.licence),
        if (m.ramMb > 0) ('Memory', 'About ${m.ramMb.round()} MB while in use'),
        if (m.languages.isNotEmpty) ('Languages', m.languageText),
        ('Checked', 'Pinned revision, exact size and SHA-256'),
      ],
      source: '',
    );
  }
}

Future<bool> askModelConsent(BuildContext context, ModelInfo m) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (context) => ConsentDialog(offer: ModelOffer.model(m)),
  );
  return r ?? false;
}

Future<bool> askDownloadConsent(BuildContext context, String model) async {
  final offer = ModelOffer.of(model);
  final r = await showDialog<bool>(
    context: context,
    builder: (context) => ConsentDialog(offer: offer),
  );
  return r ?? false;
}

class ConsentDialog extends StatelessWidget {
  const ConsentDialog({super.key, required this.offer});
  final ModelOffer offer;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return NbDialog(
      title: offer.title,
      width: 500,
      body: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(offer.what),
          const SizedBox(height: NbSpace.x4),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: c.raised,
              borderRadius: NbRadius.rowAll,
              border: Border.all(color: c.line),
            ),
            child: Column(
              children: [
                for (final (k, v) in offer.facts)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(width: 86, child: Text(k, style: NbType.text(NbSize.small, c.dim))),
                        Expanded(child: Text(v, style: NbType.data(12, c.text, height: 1.45))),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: NbSpace.x4),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(width: 3, height: 38, margin: const EdgeInsets.only(right: 12, top: 2), color: c.orange),
              Expanded(
                child: Text(
                  "This is NOBAD Find's only internet connection. Your files, your index and your searches stay on "
                  'this PC.',
                  style: NbType.text(13, c.text, height: 1.5),
                ),
              ),
            ],
          ),
        ],
      ),
      actions: [
        // no download by pressing Enter: "Not now" has the focus
        NbButton('Not now', kind: NbButtonKind.ghost, autofocus: true, onPressed: () => Navigator.pop(context, false)),
        NbButton('Download', onPressed: () => Navigator.pop(context, true)),
      ],
    );
  }
}
