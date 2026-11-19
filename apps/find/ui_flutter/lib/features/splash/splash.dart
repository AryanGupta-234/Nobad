/// The splash while the engine connects (usually a fraction of a second): the mark, NOBAD FIND, and the line
/// from 0.7.0's splash image. It fades away as soon as the engine answers, or says it isn't running.
library;

import 'package:flutter/widgets.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/typography.dart';
import '../../widgets/common.dart';
import '../../widgets/panels.dart';

class Splash extends StatelessWidget {
  const Splash({super.key});

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return ColoredBox(
      color: c.bg,
      child: Center(
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Transform.rotate(angle: -.12, child: const NbMark(size: 92)),
            const SizedBox(width: 28),
            Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('NOBAD', style: NbType.display(36, c.text)),
                Text('FIND', style: NbType.display(36, c.orange)),
                const SizedBox(height: 10),
                const SignalRule(width: 38),
                const SizedBox(height: 12),
                Text('Private file search. Offline.', style: NbType.data(12, c.muted)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
