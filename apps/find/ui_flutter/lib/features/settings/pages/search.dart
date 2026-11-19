/// Search: what happens when you open a file, the quick find bar, and the recent searches this window keeps.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../widgets/controls.dart';
import '../settings_parts.dart';

class SearchSettingsPage extends StatelessWidget {
  const SearchSettingsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final recent = AppScope.of(context).find.recent;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SettingsGroup(
          'Opening files',
          rows: [
            SwitchSetting(
              'hide_after_open',
              'Hide after opening a file',
              'Off: the window stays up after Enter opens a file. On: it hides, like a launcher.',
            ),
          ],
        ),
        const SettingsGroup(
          'Quick find bar',
          rows: [
            SwitchSetting(
              'bar',
              'Quick find bar',
              'A small search box on its own shortcut that shows over whatever you are doing. Takes effect at the '
                  'next start.',
            ),
          ],
        ),
        if (recent != null)
          SettingsGroup(
            'Recent searches',
            rows: [
              ListenableBuilder(
                listenable: recent,
                builder: (context, _) => SettingRow(
                  label: 'Recent searches',
                  help: recent.items.isEmpty
                      ? 'None kept. Searches you open a file from show under the empty box.'
                      : '${recent.items.length} kept on this PC only (never sent anywhere), shown under the empty box.',
                  control: NbButton(
                    'Clear',
                    small: true,
                    kind: NbButtonKind.ghost,
                    onPressed: recent.items.isEmpty ? null : () => unawaited(recent.clear()),
                  ),
                ),
              ),
            ],
          ),
      ],
    );
  }
}
