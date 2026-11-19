/// The line at the foot of Search: the level glyph, "48,210 files indexed · Working gently · Reading text", the
/// governor's reason, and Details (the Index page). From status and level events only.
library;

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine_api.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

class StatusLine extends StatelessWidget {
  const StatusLine({super.key});

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
          height: 38,
          padding: const EdgeInsets.symmetric(horizontal: 24),
          color: c.rail,
          child: Row(children: [
            LevelGlyph(level: ok ? (st?.levelKey ?? 'light') : 'paused', color: c.orange, dim: c.dim, size: 10),
            const SizedBox(width: 10),
            Flexible(
              child: Semantics(
                liveRegion: false,
                child: Text(s.status.line, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: NbType.data(NbSize.caption, s.status.link == Link.offline ? c.warn : c.muted)),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Text(reason, maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: TextAlign.right,
                  style: NbType.text(NbSize.small, c.dim)),
            ),
            const SizedBox(width: 14),
            Pressable(
              onTap: () => s.nav.go(AppTab.indexing),
              semanticLabel: 'Details',
              builder: (context, p) => Text('Details',
                  style: NbType.text(NbSize.small, c.orange, weight: FontWeight.w600).copyWith(
                      decoration: p.lit ? TextDecoration.underline : TextDecoration.none,
                      decorationColor: c.orange)),
            ),
          ]),
        );
      },
    );
  }
}
