/// Privacy: the Windows Search switch (elevated helper, undoable) and deleting the whole index.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../../app/scope.dart';
import '../../../app/theme/colors.dart';
import '../../../app/theme/typography.dart';
import '../../../widgets/controls.dart';
import '../../../widgets/dialogs.dart';
import '../settings_parts.dart';

class PrivacyPage extends StatelessWidget {
  const PrivacyPage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    final ws = s.settings.wsearch;
    Widget wsHelp;
    Widget? wsControl;
    if (ws == null || ws.missing) {
      wsHelp = Text(
        ws == null ? '' : "Windows Search isn't installed on this PC.",
        style: NbType.text(12.5, c.dim, height: 1.5),
      );
    } else {
      final off = ws.off;
      wsHelp = Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: off
                  ? 'Done: Windows Search indexing is off and NOBAD Find starts with Windows. '
                  : 'Windows Search indexing is on (${ws.start}${ws.running ? ', running' : ''}). One click turns it '
                        'off and starts NOBAD Find with Windows. ',
            ),
            TextSpan(
              text:
                  'With it off, the Start menu, Explorer and Outlook stop finding files by their content (NOBAD '
                  'Find does that instead). Windows asks for permission once; going back restores exactly the '
                  'setting it had before.',
              style: TextStyle(color: c.warn),
            ),
          ],
        ),
        style: NbType.text(12.5, c.dim, height: 1.5),
      );
      wsControl = NbButton(
        s.settings.wsearchBusy ? 'Waiting for Windows…' : (off ? 'Go back to Windows Search' : 'Switch to NOBAD Find'),
        kind: off ? NbButtonKind.ghost : NbButtonKind.primary,
        onPressed: s.settings.wsearchBusy ? null : () => unawaited(s.settings.toggleWindowsSearch()),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SettingsGroup(
          'Windows Search',
          rows: [SettingRow(label: 'Use NOBAD Find instead of Windows Search', helpWidget: wsHelp, control: wsControl)],
        ),
        SettingsGroup(
          'Your data',
          rows: [
            SettingRow(
              label: 'Delete the whole index',
              help: 'Removes everything NOBAD Find has stored. It starts again from scratch.',
              control: NbButton(
                'Delete index',
                kind: NbButtonKind.danger,
                onPressed: () => unawaited(s.settings.wipe(() => typeDeleteDialog(context))),
              ),
            ),
          ],
        ),
      ],
    );
  }
}
