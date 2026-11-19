/// First run: what NOBAD Find does with your files (and doesn't), the two shortcuts, how it stays out of the way,
/// and an optional meaning search (with the consent dialog). "Start searching" remembers it was seen.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../widgets/common.dart';
import '../../widgets/controls.dart';
import '../../widgets/panels.dart';
import '../consent/download_consent_dialog.dart';

class Welcome extends StatelessWidget {
  const Welcome({super.key});

  static String keysOf(String hotkey) => hotkey
      .split('+')
      .map((k) => k.isEmpty ? k : k[0].toUpperCase() + k.substring(1))
      .join('+');

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final st = s.settings.settings;
    return ColoredBox(
      color: c.bg,
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(72, 56, 72, 40),
        child: Align(
          alignment: Alignment.topLeft,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const NbMark(size: 44),
              const SizedBox(height: NbSpace.x8),
              Semantics(
                header: true,
                child: Text('Your files.\nFound in a moment.\nNever sent anywhere.'.toUpperCase(),
                    style: NbType.display(40, c.text)),
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
                    style: NbType.text(15, c.muted, height: 1.6)),
              ),
              const SizedBox(height: NbSpace.x8),
              _Fact(keys: keysOf(st.text('hotkey')), text: 'Opens this window from anywhere.'),
              if (st.flag('bar'))
                _Fact(keys: keysOf(st.text('bar_hotkey')),
                    text: 'The quick find bar: a small search box over whatever you are doing.'),
              const _Fact(
                  text: 'It slows down or pauses while you play, present, take a call or run on battery, and '
                      'shows you why on the Index page.'),
              const SizedBox(height: NbSpace.x6),
              NbPanel(
                padding: const EdgeInsets.fromLTRB(18, 14, 14, 14),
                child: Row(children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('Search by meaning (optional)',
                          style: NbType.text(14, c.text, weight: FontWeight.w600)),
                      const SizedBox(height: 3),
                      Text('Finds “lease agreement” when you type “rent”. A one-time 23 MB download, then it runs on '
                          'this PC only.', style: NbType.text(NbSize.small, c.dim, height: 1.5)),
                    ]),
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
                      return NbButton('Download…', kind: NbButtonKind.ghost, small: true, onPressed: () {
                        unawaited(s.settings.download('meaning', consent: () => askDownloadConsent(context, 'meaning')));
                      });
                    },
                  ),
                ]),
              ),
              const SizedBox(height: NbSpace.x8),
              Row(children: [
                NbButton('Start searching', autofocus: true, onPressed: () => s.settings.set('welcome_seen', true)),
                const Spacer(),
                Text('Software with a point of view.', style: NbType.text(NbSize.small, c.dim)),
              ]),
            ]),
          ),
        ),
      ),
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
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(
          width: 190,
          child: keys == null
              ? Align(
                  alignment: Alignment.topLeft,
                  child: Container(width: 22, height: 2, margin: const EdgeInsets.only(top: 10, left: 2), color: c.orange))
              : Wrap(spacing: 3, runSpacing: 3, children: [for (final k in keys!.split('+')) Kbd(k)]),
        ),
        Expanded(child: Text(text, style: NbType.text(14, c.text, height: 1.5))),
      ]),
    );
  }
}
