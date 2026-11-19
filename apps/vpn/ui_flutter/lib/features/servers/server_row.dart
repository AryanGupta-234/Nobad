/// One server: its name and place, the endpoint in Cascadia Mono, the measured latency as a bar and a number,
/// the favourite star. A press connects (or disconnects the one that's up). Rows move on a spring when the order
/// changes ([SpringColumn]).
library;

import 'package:flutter/physics.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/models.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';
import '../../widgets/pressable.dart';

/// Row heights: the Servers screen, and the compact list on Home.
const rowHeight = 52.0;
const compactRowHeight = 44.0;

class ServerRow extends StatelessWidget {
  const ServerRow({
    super.key,
    required this.region,
    required this.active,
    required this.connecting,
    required this.favorite,
    required this.onTap,
    required this.onStar,
    this.onEdit,
    this.dense = false,
    this.selected = false,
    this.located = true,
    this.onConnect,
  });
  final Region region;
  final bool active;
  final bool connecting;
  final bool favorite;
  final VoidCallback? onTap;
  final VoidCallback onStar;
  final VoidCallback? onEdit;
  final bool dense;

  /// Picked in the list or on the map (an orange edge); [onTap] selects, [onConnect] connects or disconnects.
  final bool selected;

  /// False: neither the engine nor the name says where it is; the row says "location unknown".
  final bool located;
  final VoidCallback? onConnect;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final p = region.ping;
    final grade = p?.grade ?? 'none';
    final q = switch (grade) {
      'fast' => c.sealed,
      'fair' => c.amber,
      'slow' => c.blocked,
      _ => c.dim,
    };
    final frac = p?.rtt == null ? 0.0 : (1 - (p!.rtt! / 300)).clamp(.08, 1.0);
    final stateWord = active ? 'connected' : (connecting ? 'connecting' : null);
    return Pressable(
      onTap: onTap,
      selected: active,
      ringRadius: NbRadius.rowAll,
      semanticLabel: [
        region.name,
        if (region.place.isNotEmpty) region.place,
        p?.rtt == null ? 'not tested' : '${p!.rtt!.round()} milliseconds',
        ?stateWord,
      ].join(', '),
      builder: (context, s) => AnimatedContainer(
        duration: NbMotion.of(context, NbMotion.fast),
        curve: NbMotion.curve,
        transform: Matrix4.translationValues(0, s.lit && !active ? -1 : 0, 0),
        height: dense ? compactRowHeight : rowHeight - 4,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          color: active ? c.sealed.withValues(alpha: c.isDark ? .09 : .08) : (selected ? c.orangeA(.08) : (s.lit ? c.cardHover : c.card)),
          borderRadius: NbRadius.rowAll,
          border: Border.all(
            color: active
                ? c.sealed.withValues(alpha: .45)
                : connecting
                ? c.amber.withValues(alpha: .5)
                : selected
                ? c.orangeA(.7)
                : (s.lit ? c.orangeA(.45) : c.line),
          ),
          boxShadow: [if (s.lit && !active) BoxShadow(color: c.orangeA(.20), blurRadius: 14, spreadRadius: -5)],
        ),
        child: Row(
          children: [
            Container(
              width: 26,
              height: 26,
              alignment: Alignment.center,
              decoration: BoxDecoration(borderRadius: NbRadius.controlAll, color: c.raised, border: Border.all(color: c.line)),
              child: Text(region.country.isEmpty ? '··' : region.country, style: NbType.data(12, c.muted)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(region.name, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: NbType.text(NbSize.body, c.text, weight: FontWeight.w600, height: 1.25)),
                  Text(
                    [
                      if (region.place.isNotEmpty) region.place else if (!located) 'location unknown',
                      dense ? region.host : region.endpoint,
                    ].join('   '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: NbType.data(12, c.muted, height: 1.4),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(p?.rtt == null ? 'not tested' : '${p!.estimate ? '≈' : ''}${p.rtt!.round()} ms',
                    style: p?.rtt == null ? NbType.text(NbSize.caption, c.dim) : NbType.data(NbSize.small, c.text)),
                const SizedBox(height: 4),
                Container(
                  width: 44,
                  height: 3,
                  decoration: BoxDecoration(color: c.raised, borderRadius: NbRadius.pillAll),
                  alignment: Alignment.centerLeft,
                  child: FractionallySizedBox(
                    widthFactor: frac,
                    child: Container(decoration: BoxDecoration(color: q, borderRadius: NbRadius.pillAll)),
                  ),
                ),
              ],
            ),
            if (onConnect != null) ...[
              const SizedBox(width: 8),
              SizedBox(
                width: 84,
                child: Align(
                  alignment: Alignment.centerRight,
                  child: NbButton(
                    active ? 'Disconnect' : (connecting ? 'Cancel' : 'Connect'),
                    small: true,
                    kind: active || connecting ? NbButtonKind.ghost : NbButtonKind.primary,
                    onPressed: onConnect,
                  ),
                ),
              ),
            ],
            if (onEdit != null)
              _Mini(glyph: NbGlyph.settings, label: 'Edit ${region.name}', onTap: onEdit!, color: c.dim),
            _Mini(
              glyph: favorite ? NbGlyph.starFilled : NbGlyph.star,
              label: favorite ? 'Remove ${region.name} from favorites' : 'Add ${region.name} to favorites',
              onTap: onStar,
              color: favorite ? c.orange : c.dim,
            ),
          ],
        ),
      ),
    );
  }
}

class _Mini extends StatelessWidget {
  const _Mini({required this.glyph, required this.label, required this.onTap, required this.color});
  final NbGlyph glyph;
  final String label;
  final VoidCallback onTap;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Pressable(
      onTap: onTap,
      semanticLabel: label,
      tooltip: label,
      builder: (context, s) => Padding(
        padding: const EdgeInsets.only(left: 4),
        child: Container(
          width: 26,
          height: 26,
          alignment: Alignment.center,
          decoration: BoxDecoration(borderRadius: NbRadius.controlAll, color: s.lit ? c.raised : null),
          child: NbIcon(glyph, size: 16, color: s.lit && color == c.dim ? c.text : color),
        ),
      ),
    );
  }
}

/// Children of a fixed height, each sliding to its new place on a spring when the order changes.
class SpringColumn extends StatelessWidget {
  const SpringColumn({super.key, required this.children, this.itemHeight = rowHeight});
  final List<Widget> children; // each must have a stable Key
  final double itemHeight;

  @override
  Widget build(BuildContext context) {
    final still = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    return SizedBox(
      height: children.length * itemHeight,
      child: Stack(
        children: [
          for (var i = 0; i < children.length; i++)
            _Slot(key: children[i].key, top: i * itemHeight, height: itemHeight, still: still, child: children[i]),
        ],
      ),
    );
  }
}

class _Slot extends StatefulWidget {
  const _Slot({super.key, required this.top, required this.height, required this.still, required this.child});
  final double top;
  final double height;
  final bool still;
  final Widget child;
  @override
  State<_Slot> createState() => _SlotState();
}

class _SlotState extends State<_Slot> with SingleTickerProviderStateMixin {
  late final _y = AnimationController.unbounded(vsync: this, value: widget.top);

  @override
  void didUpdateWidget(_Slot old) {
    super.didUpdateWidget(old);
    if (old.top != widget.top) {
      if (widget.still) {
        _y.value = widget.top;
      } else {
        _y.animateWith(SpringSimulation(NbSpring.list, _y.value, widget.top, _y.velocity));
      }
    }
  }

  @override
  void dispose() {
    _y.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _y,
    builder: (context, child) => Positioned(left: 0, right: 0, top: _y.value, height: widget.height, child: child!),
    child: widget.child,
  );
}
