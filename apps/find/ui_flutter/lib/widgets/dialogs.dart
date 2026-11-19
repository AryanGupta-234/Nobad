/// Questions that need an answer before something can't be undone: confirm, and "type DELETE".
library;

import 'package:material_ui/material_ui.dart';

import '../app/theme/colors.dart';
import '../app/theme/tokens.dart';
import '../app/theme/typography.dart';
import 'controls.dart';

/// The frame every NOBAD dialog uses: a panel with a title, a body and right-aligned actions.
class NbDialog extends StatelessWidget {
  const NbDialog({super.key, required this.title, required this.body, required this.actions, this.width = 460});
  final String title;
  final Widget body;
  final List<Widget> actions;
  final double width;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Dialog(
      backgroundColor: c.surface,
      insetPadding: const EdgeInsets.all(NbSpace.x6),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: width),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(NbSpace.x6, NbSpace.x5, NbSpace.x6, NbSpace.x5),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Semantics(
              header: true,
              child: Text(title, style: NbType.text(NbSize.lead, c.text, weight: FontWeight.w600, height: 1.3)),
            ),
            const SizedBox(height: NbSpace.x3),
            DefaultTextStyle(style: NbType.text(13.5, c.muted, height: 1.55), child: body),
            const SizedBox(height: NbSpace.x5),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              for (var i = 0; i < actions.length; i++) ...[if (i > 0) const SizedBox(width: NbSpace.x2), actions[i]],
            ]),
          ]),
        ),
      ),
    );
  }
}

Future<bool> confirmDialog(BuildContext context, {required String question, required String yes,
    String no = 'Cancel', bool danger = false, String title = 'Are you sure?'}) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (context) => NbDialog(
      title: title,
      body: Text(question),
      actions: [
        NbButton(no, kind: NbButtonKind.ghost, onPressed: () => Navigator.pop(context, false)),
        NbButton(yes, kind: danger ? NbButtonKind.danger : NbButtonKind.primary, autofocus: true,
            onPressed: () => Navigator.pop(context, true)),
      ],
    ),
  );
  return r ?? false;
}

/// "This deletes the whole index. Type DELETE to confirm." Returns what was typed, or null.
Future<String?> typeDeleteDialog(BuildContext context) =>
    showDialog<String>(context: context, builder: (context) => const _TypeDelete());

class _TypeDelete extends StatefulWidget {
  const _TypeDelete();
  @override
  State<_TypeDelete> createState() => _TypeDeleteState();
}

class _TypeDeleteState extends State<_TypeDelete> {
  final _ctl = TextEditingController();

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final ok = _ctl.text == 'DELETE';
    return NbDialog(
      title: 'Delete the whole index',
      body: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('This deletes the whole index. Type DELETE to confirm.'),
        const SizedBox(height: NbSpace.x3),
        TextField(
          controller: _ctl,
          autofocus: true,
          onChanged: (_) => setState(() {}),
          onSubmitted: (_) => ok ? Navigator.pop(context, _ctl.text) : null,
          style: NbType.data(14, c.text),
          cursorColor: c.orange,
          decoration: InputDecoration(
            isDense: true,
            filled: true,
            fillColor: c.raised,
            hintText: 'DELETE',
            hintStyle: NbType.data(14, c.dim),
            contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            enabledBorder: OutlineInputBorder(borderRadius: NbRadius.controlAll, borderSide: BorderSide(color: c.line2)),
            focusedBorder: OutlineInputBorder(borderRadius: NbRadius.controlAll, borderSide: BorderSide(color: c.danger)),
          ),
        ),
      ]),
      actions: [
        NbButton('Cancel', kind: NbButtonKind.ghost, onPressed: () => Navigator.pop(context)),
        NbButton('Delete index', kind: NbButtonKind.danger, onPressed: ok ? () => Navigator.pop(context, _ctl.text) : null),
      ],
    );
  }
}
