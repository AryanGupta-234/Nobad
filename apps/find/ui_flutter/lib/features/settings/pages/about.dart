/// About: the version, what NOBAD Find is, the licence and source, and Quit.
library;

import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/tokens.dart';
import '../../../app/theme/typography.dart';
import '../../../widgets/common.dart';
import '../../../widgets/controls.dart';
import '../settings_parts.dart';

const sourceLink = 'github.com/nobad-studio/Nobad-VPN';

class AboutPage extends StatelessWidget {
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final v = s.status.details?.version ?? '';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SettingsGroup('NOBAD Find', rows: [
        Padding(
          padding: const EdgeInsets.all(NbSpace.x5),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const NbMark(size: 52),
            const SizedBox(width: NbSpace.x5),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Version ${v.isNotEmpty ? v : s.version}'.toUpperCase(), style: NbType.display(22, c.text)),
                const SizedBox(height: 8),
                Text('Private, offline file search for Windows. Your files, your index and your searches stay on '
                    'this PC.', style: NbType.text(14, c.muted, height: 1.55)),
                const SizedBox(height: 6),
                Text('Open source under the MIT licence. Source and releases: $sourceLink',
                    style: NbType.data(12, c.dim, height: 1.6)),
                const SizedBox(height: 14),
                Text('NOBAD. Software with a point of view.', style: NbType.text(13, c.text, weight: FontWeight.w600)),
              ]),
            ),
            const SizedBox(width: NbSpace.x4),
            NbButton('Copy link', kind: NbButtonKind.ghost, small: true, onPressed: () async {
              try {
                await Clipboard.setData(const ClipboardData(text: 'https://$sourceLink'));
                s.toasts.show('Link copied.');
              } on Object {
                s.toasts.show("Couldn't copy the link.");
              }
            }),
          ]),
        ),
      ]),
      SettingsGroup('Quit', rows: [
        SettingRow(
          label: 'Quit NOBAD Find',
          help: 'Closing the window stops indexing and leaves NOBAD Find as one small idle process so the hotkey '
              'still works (unless Keep indexing in the background is on). This stops it completely until you '
              'start it again.',
          control: NbButton('Quit', kind: NbButtonKind.ghost, onPressed: () => unawaited(s.settings.quit())),
        ),
      ]),
    ]);
  }
}
