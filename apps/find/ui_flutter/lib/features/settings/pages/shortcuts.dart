/// Shortcuts: the two global hotkeys (the engine owns them) and the keys inside the window.
library;

import 'package:flutter/widgets.dart';

import '../../../app/theme/colors.dart';
import '../../../app/theme/typography.dart';
import '../../../widgets/controls.dart';
import '../settings_parts.dart';

const _keys = [
  (['Ctrl', '1'], 'Search'),
  (['Ctrl', '2'], 'Index'),
  (['Ctrl', '3'], 'Settings'),
  (['↑', '↓'], 'Move through the results'),
  (['PgUp', 'PgDn'], 'A page of results'),
  (['Home', 'End'], 'First or last result'),
  (['Tab'], 'Use the suggested filter'),
  (['Enter'], 'Open'),
  (['Ctrl', 'Enter'], 'Show in folder'),
  (['Ctrl', 'Shift', 'Enter'], 'Open with…'),
  (['Ctrl', 'C'], 'Copy path'),
  (['Shift', 'Del'], 'Forget…'),
  (['Space'], 'Details (narrow window)'),
  (['Shift', 'F10'], 'Actions menu'),
  (['Esc'], 'Clear the box, then hide'),
];

class ShortcutsPage extends StatelessWidget {
  const ShortcutsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SettingsGroup(
          'Anywhere in Windows',
          rows: [
            TextSetting(
              'hotkey',
              'Open NOBAD Find',
              'For example win+shift+space or ctrl+alt+f. Takes effect at the next start.',
            ),
            TextSetting(
              'bar_hotkey',
              'Quick find bar',
              'For example ctrl+alt+space or win+alt+f. Takes effect at the next start.',
            ),
          ],
        ),
        SettingsGroup(
          'In this window',
          rows: [
            for (final (keys, what) in _keys)
              SizedBox(
                height: 36,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14),
                  child: Row(
                    children: [
                      Expanded(child: Text(what, style: NbType.text(13, c.text, height: 1.2))),
                      for (final k in keys) ...[const SizedBox(width: 4), Kbd(k)],
                    ],
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }
}
