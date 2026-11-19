/// General: look and launch.
library;

import 'package:flutter/widgets.dart';

import '../settings_parts.dart';

class GeneralPage extends StatelessWidget {
  const GeneralPage({super.key});

  @override
  Widget build(BuildContext context) => const Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      SettingsGroup(
        'Look and launch',
        rows: [
          ChoiceSetting('theme', 'Theme', 'Dark or light. Applies right away.', [('dark', 'Dark'), ('light', 'Light')]),
          SwitchSetting(
            'glass',
            'See-through window',
            "Windows 11 Mica behind the window. Follows Windows' own Transparency effects switch.",
          ),
          TextSetting('hotkey', 'Hotkey', 'For example win+shift+space or ctrl+alt+f. Takes effect at the next start.'),
          SwitchSetting(
            'bar',
            'Quick find bar',
            'A small search box on its own shortcut that shows over whatever you are doing. Takes effect at the '
                'next start.',
          ),
          TextSetting(
            'bar_hotkey',
            'Quick find bar shortcut',
            'For example ctrl+alt+space or win+alt+f. Takes effect at the next start.',
          ),
          SwitchSetting(
            'hide_after_open',
            'Hide after opening a file',
            'Off: the window stays up after Enter opens a file. On: it hides, like a launcher.',
          ),
          SwitchSetting('autostart', 'Start with Windows', 'Starts hidden; the hotkey opens it.'),
        ],
      ),
    ],
  );
}
