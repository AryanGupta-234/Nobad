/// The line at the foot of Search: the level glyph, "48,210 files indexed · Working gently · Reading text", the
/// governor's reason, and Details (the Index page). From status and level events only.
library;

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

class StatusLine extends StatelessWidget {
  const StatusLine({super.key, this.keys = false});

  /// Results on screen: the keys for them on the left.
  final bool keys;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: s.status,
      builder: (context, _) {
        final st = s.status.status;
        final ok = s.status.connected;
        final reason = ok ? (st?.reason ?? '') : '';
        return Container(
          height: 36,
          margin: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, 0),
          decoration: BoxDecoration(
            border: Border(top: BorderSide(color: c.line)),
          ),
          child: Row(
            children: [
              if (keys) ...[
                // as many keys as fit; the rest are in the Ctrl+K panel
                const Expanded(
                  child: ClipRect(
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      physics: NeverScrollableScrollPhysics(),
                      child: KeyHints([
                        (['Ctrl+K'], 'Actions'),
                        (['↵'], 'Open'),
                        (['Ctrl+↵'], 'Show in folder'),
                        (['Ctrl+Shift+↵'], 'Open with'),
                      ]),
                    ),
                  ),
                ),
                const SizedBox(width: 16),
              ],
              LevelGlyph(level: ok ? (st?.levelKey ?? 'light') : 'paused', color: c.orange, dim: c.dim, size: 10),
              const SizedBox(width: 10),
              Flexible(
                flex: keys ? 0 : 1,
                // beside the keys only the phase, and never more than a short line: the keys come first
                child: ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: keys ? 220 : double.infinity),
                  child: Semantics(
                    liveRegion: false,
                    child: Text(
                      keys && ok ? (st?.phaseLabel ?? '') : s.status.line,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: NbType.text(NbSize.caption, s.status.link == Link.offline ? c.warn : c.muted),
                    ),
                  ),
                ),
              ),
              if (!keys) ...[
                const SizedBox(width: 16),
                Expanded(
                  child: Text(
                    reason,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.right,
                    style: NbType.text(NbSize.small, c.dim),
                  ),
                ),
              ],
              const SizedBox(width: 14),
              Pressable(
                onTap: () => s.nav.go(AppTab.indexing),
                semanticLabel: 'Details',
                builder: (context, p) => Text(
                  'Details',
                  style: NbType.text(NbSize.small, c.orange, weight: FontWeight.w600).copyWith(
                    decoration: p.lit ? TextDecoration.underline : TextDecoration.none,
                    decorationColor: c.orange,
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
