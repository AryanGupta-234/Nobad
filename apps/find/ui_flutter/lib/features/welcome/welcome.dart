/// First run: what NOBAD Find does with your files (and doesn't), the two shortcuts, how it stays out of the way,
/// and an optional meaning search (with the consent dialog). "Start searching" remembers it was seen.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../widgets/smooth_scroll.dart';
import '../../widgets/common.dart';
import '../../widgets/controls.dart';
import '../../widgets/panels.dart';
import '../../engine/models/models_info.dart';
import '../consent/download_consent_dialog.dart';
import '../settings/pages/models.dart' show HardwareTiles, tierWhy;

class Welcome extends StatelessWidget {
  const Welcome({super.key});

  static String keysOf(String hotkey) =>
      hotkey.split('+').map((k) => k.isEmpty ? k : k[0].toUpperCase() + k.substring(1)).join('+');

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final st = s.settings.settings;
    return ColoredBox(
      color: c.bg,
      child: SmoothScroll(builder: (sc) => SingleChildScrollView(controller: sc, 
        padding: const EdgeInsets.fromLTRB(48, 32, 48, 24),
        child: Align(
          alignment: Alignment.topLeft,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const NbMark(size: 40),
                const SizedBox(height: NbSpace.x6),
                Semantics(
                  header: true,
                  child: Text(
                    'Your files.\nFound in a moment.\nNever sent anywhere.'.toUpperCase(),
                    style: NbType.display(24, c.text),
                  ),
                ),
                const SizedBox(height: NbSpace.x5),
                const SignalRule(),
                const SizedBox(height: NbSpace.x5),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 580),
                  child: Text(
                    'NOBAD Find reads the names and the text inside the files on this PC and keeps an encrypted '
                    'index in your own profile folder. Searching never uses the internet: your files, your index '
                    'and your searches stay on this PC.',
                    style: NbType.text(14, c.muted, height: 1.55),
                  ),
                ),
                const SizedBox(height: NbSpace.x6),
                _Fact(keys: keysOf(st.text('hotkey')), text: 'Opens this window from anywhere.'),
                if (st.flag('bar'))
                  _Fact(
                    keys: keysOf(st.text('bar_hotkey')),
                    text: 'The quick find bar: a small search box over whatever you are doing.',
                  ),
                const _Fact(
                  text:
                      'It slows down or pauses while you play, present, take a call or run on battery, and '
                      'shows you why on the Index page.',
                ),
                const _YourPc(),
                const SizedBox(height: NbSpace.x3),
                NbPanel(
                  padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Search by meaning (optional)',
                              style: NbType.text(14, c.text, weight: FontWeight.w600),
                            ),
                            const SizedBox(height: 3),
                            Text(
                              'Finds “lease agreement” when you type “rent”. A one-time 23 MB download, then it runs on '
                              'this PC only.',
                              style: NbType.text(NbSize.small, c.dim, height: 1.5),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: NbSpace.x4),
                      ListenableBuilder(
                        listenable: s.status,
                        builder: (context, _) {
                          final m = s.status.model('meaning');
                          if (m.ready) return Text('Ready', style: NbType.text(13, c.orange, weight: FontWeight.w600));
                          if (m.downloading) {
                            return Text('Downloading… ${m.percent}%', style: NbType.data(12, c.orange));
                          }
                          return NbButton(
                            'Download…',
                            kind: NbButtonKind.ghost,
                            small: true,
                            onPressed: () {
                              unawaited(
                                s.settings.download('meaning', consent: () => askDownloadConsent(context, 'meaning')),
                              );
                            },
                          );
                        },
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: NbSpace.x6),
                Row(
                  children: [
                    NbButton('Start searching', autofocus: true, onPressed: () => s.settings.set('welcome_seen', true)),
                    const Spacer(),
                    Text('Software with a point of view.', style: NbType.text(NbSize.small, c.dim)),
                  ],
                ),
              ],
            ),
          ),
        ),
      )),
    );
  }
}

/// One line of what NOBAD Find does: the key caps that do it (if any), then the sentence.
class _Fact extends StatelessWidget {
  const _Fact({this.keys, required this.text});
  final String? keys;
  final String text;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: NbSpace.x3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 190,
            child: keys == null
                ? Align(
                    alignment: Alignment.topLeft,
                    child: Container(
                      width: 22,
                      height: 2,
                      margin: const EdgeInsets.only(top: 10, left: 2),
                      color: c.orange,
                    ),
                  )
                : Wrap(spacing: 3, runSpacing: 3, children: [for (final k in keys!.split('+')) Kbd(k)]),
          ),
          Expanded(child: Text(text, style: NbType.text(13.5, c.text, height: 1.5))),
        ],
      ),
    );
  }
}

/// This PC and the model tier recommended for it (the engine's `models`); nothing when the engine can't say.
class _YourPc extends StatefulWidget {
  const _YourPc();

  @override
  State<_YourPc> createState() => _YourPcState();
}

class _YourPcState extends State<_YourPc> {
  ModelsInfo? _info;
  bool _asked = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_asked) return;
    _asked = true;
    unawaited(_load());
  }

  Future<void> _load() async {
    try {
      final m = await AppScope.of(context).engine.models();
      if (mounted) setState(() => _info = m);
    } on Object {
      // an older engine or none: no PC block (never made-up numbers)
    }
  }

  @override
  Widget build(BuildContext context) {
    final info = _info;
    if (info == null || info.pc == null) return const SizedBox(height: NbSpace.x3);
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: NbSpace.x3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionTitle('Your PC', top: 0),
          HardwareTiles(info.pc),
          if (info.tierRecommended.isNotEmpty) ...[
            const SizedBox(height: NbSpace.x2),
            Row(
              children: [
                Expanded(
                  child: Text.rich(
                    TextSpan(
                      children: [
                        TextSpan(
                          text: 'Recommended models for this PC: ${tierLabel(info.tierRecommended)}. ',
                          style: NbType.text(13, c.text, weight: FontWeight.w600),
                        ),
                        TextSpan(text: tierWhy(info.tierRecommended)),
                      ],
                    ),
                    style: NbType.text(12, c.dim, height: 1.45),
                  ),
                ),
                const SizedBox(width: NbSpace.x3),
                NbButton(
                  'See models',
                  small: true,
                  kind: NbButtonKind.ghost,
                  onPressed: () {
                    unawaited(s.settings.set('welcome_seen', true));
                    s.nav.openSettings(SettingsPage.models);
                  },
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
