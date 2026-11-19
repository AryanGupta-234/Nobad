/// Performance: staying out of your way, and the apps NOBAD Find has learned.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/tokens.dart';
import '../../../app/theme/typography.dart';
import '../../../engine/models/format.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/dialogs.dart';
import '../settings_parts.dart';

class PerformancePage extends StatelessWidget {
  const PerformancePage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final learned = s.settings.learned;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SettingsGroup(
          'Staying out of your way',
          rows: [
            ChoiceSetting(
              'games_mode',
              'Games and presentations',
              'Smart slows down or pauses only for the apps that really need your PC, and learns which ones. Always '
                  "pause stops whenever a game is running. Don't change never reacts to games. Presentations always "
                  'pause NOBAD Find.',
              [('smart', 'Smart (recommended)'), ('always', 'Always pause'), ('off', "Don't change")],
            ),
            SwitchSetting('pause_on_battery', 'Pause on battery', ''),
            SwitchSetting('pause_on_call', 'Pause during calls', 'While an app uses the microphone or camera.'),
            SwitchSetting(
              'keep_background',
              'Keep indexing in the background',
              'Closing the window stops indexing and every worker; NOBAD Find stays as one small idle process so the '
                  'hotkey works. On: keeps indexing after closing.',
            ),
            SwitchSetting(
              'tray',
              'Show NOBAD Find in the notification area',
              'The icon works with the window closed: open NOBAD Find, the quick find bar, pause and quit.',
            ),
            TextSetting(
              'workers',
              'Text reading workers',
              "0 = choose from your CPU: two threads stay free while you use the PC, one when you're away.",
              number: true,
            ),
          ],
        ),
        SettingsGroup(
          'Apps NOBAD Find has learned',
          rows: [
            SettingRow(
              label: 'Apps that slowed your PC down',
              help:
                  'When an app lagged while NOBAD Find was working, NOBAD Find remembers the app\'s file name '
                  '(nothing else) and starts gentler next time.',
              control: learned.isEmpty
                  ? null
                  : NbButton(
                      'Reset all',
                      kind: NbButtonKind.ghost,
                      small: true,
                      onPressed: () {
                        unawaited(
                          s.settings.forgetApp(
                            null,
                            confirm: () => confirmDialog(
                              context,
                              title: 'Reset all',
                              question: 'Forget every app NOBAD Find has learned?',
                              yes: 'Forget all',
                              danger: true,
                            ),
                          ),
                        );
                      },
                    ),
              below: learned.isEmpty
                  ? Text(
                      'None yet. When an app lags while NOBAD Find works, it shows up here.',
                      style: NbType.text(13, c.dim),
                    )
                  : Column(
                      children: [
                        for (final a in learned)
                          Container(
                            margin: const EdgeInsets.only(bottom: 6),
                            padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
                            decoration: BoxDecoration(
                              border: Border.all(color: c.line),
                              borderRadius: NbRadius.rowAll,
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(a.bare, style: NbType.text(13.5, c.text, weight: FontWeight.w600)),
                                      Text(
                                        '${a.reason} Seen ${groupDigits(a.seen)} ${a.seen == 1 ? 'time' : 'times'}.',
                                        style: NbType.text(NbSize.small, c.dim, height: 1.45),
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 12),
                                NbButton(
                                  'Forget',
                                  kind: NbButtonKind.ghost,
                                  small: true,
                                  onPressed: () => unawaited(s.settings.forgetApp(a.exe)),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
            ),
          ],
        ),
      ],
    );
  }
}
