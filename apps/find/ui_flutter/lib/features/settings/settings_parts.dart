/// The parts every Settings page is built from: a group (titled panel) of rows; a row is a label, its help, and
/// one control. Switches, choices, fields and folder lists write through SettingsController (the engine checks).
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../widgets/controls.dart';
import '../../widgets/glass.dart';
import '../../widgets/panels.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

class SettingsGroup extends StatelessWidget {
  const SettingsGroup(this.title, {super.key, required this.rows});
  final String title;
  final List<Widget> rows;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: NbSpace.x5),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 2, bottom: 6),
            child: Semantics(header: true, child: Text(title, style: sectionStyle(c))),
          ),
          Glass(
            radius: 10,
            child: Column(
              children: [
                for (var i = 0; i < rows.length; i++) ...[if (i > 0) Container(height: 1, color: c.line), rows[i]],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// One setting: what it is, what it means, and its control on the right; [below] spans the row (folder lists).
class SettingRow extends StatelessWidget {
  const SettingRow({super.key, required this.label, this.help = '', this.helpWidget, this.control, this.below});
  final String label;
  final String help;
  final Widget? helpWidget;
  final Widget? control;
  final Widget? below;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 44),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 8, 12, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (label.isNotEmpty)
                        Text(label, style: NbType.text(13.5, c.text, weight: FontWeight.w600, height: 1.35)),
                      if (helpWidget != null)
                        Padding(padding: const EdgeInsets.only(top: 2), child: helpWidget!)
                      else if (help.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 560),
                            child: Text(help, style: NbType.text(NbSize.small, c.dim, height: 1.4)),
                          ),
                        ),
                    ],
                  ),
                ),
                if (control != null) ...[const SizedBox(width: NbSpace.x4), control!],
              ],
            ),
            if (below != null) ...[const SizedBox(height: NbSpace.x2), below!],
          ],
        ),
      ),
    );
  }
}

class SwitchSetting extends StatelessWidget {
  const SwitchSetting(this.k, this.label, this.help, {super.key});
  final String k;
  final String label;
  final String help;

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    return SettingRow(
      label: label,
      help: help,
      control: NbSwitch(value: s.settings.flag(k), label: label, onChanged: (v) => s.set(k, v)),
    );
  }
}

class ChoiceSetting extends StatelessWidget {
  const ChoiceSetting(this.k, this.label, this.help, this.options, {super.key});
  final String k;
  final String label;
  final String help;
  final List<(String, String)> options;

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    return SettingRow(
      label: label,
      help: help,
      control: NbSelect(
        label: label,
        value: s.settings.text(k),
        options: options,
        maxWidth: 230,
        onChanged: (v) => s.set(k, v),
      ),
    );
  }
}

class TextSetting extends StatelessWidget {
  const TextSetting(this.k, this.label, this.help, {super.key, this.number = false});
  final String k;
  final String label;
  final String help;
  final bool number;

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    return SettingRow(
      label: label,
      help: help,
      control: NbField(
        label: label,
        number: number,
        value: number ? '${s.settings.number(k)}' : s.settings.text(k),
        onSubmit: (v) => s.set(k, number ? (int.tryParse(v) ?? -1) : v.trim()),
      ),
    );
  }
}

class FoldersSetting extends StatelessWidget {
  const FoldersSetting(this.k, this.label, this.help, {super.key});
  final String k;
  final String label;
  final String help;

  @override
  Widget build(BuildContext context) =>
      ListenableBuilder(listenable: AppScope.of(context).settings, builder: (context, _) => _build(context));

  Widget _build(BuildContext context) {
    final s = AppScope.of(context).settings;
    final c = NbColors.of(context);
    final list = s.settings.list(k);
    return SettingRow(
      label: label,
      help: help,
      control: NbButton(
        'Add folder',
        kind: NbButtonKind.ghost,
        small: true,
        icon: NbGlyph.plus,
        onPressed: () => unawaited(s.pickAndAdd(k)),
      ),
      below: list.isEmpty
          ? null
          : Column(
              children: [
                for (var i = 0; i < list.length; i++)
                  Container(
                    margin: const EdgeInsets.only(bottom: 6),
                    padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
                    decoration: BoxDecoration(
                      border: Border.all(color: c.line),
                      borderRadius: NbRadius.controlAll,
                    ),
                    child: Row(
                      children: [
                        Expanded(child: Text(list[i], style: NbType.data(12, c.muted))),
                        Pressable(
                          onTap: () => s.removeFolder(k, i),
                          semanticLabel: 'Remove ${list[i]}',
                          tooltip: 'Remove',
                          builder: (context, p) => Padding(
                            padding: const EdgeInsets.all(6),
                            child: NbIcon(NbGlyph.close, size: 14, color: p.lit ? c.orange : c.dim),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
    );
  }
}
