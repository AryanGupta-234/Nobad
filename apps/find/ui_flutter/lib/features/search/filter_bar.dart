/// The filter bar under the search box: kind, date, size, folder, order (0.7.0 labels), "Here" when the window
/// was opened from a File Explorer folder, and Clear filters. Filters combine with whatever the words say.
library;

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../state/settings_controller.dart' show errorText;
import '../../engine/engine_api.dart' show FolderPick;
import '../../engine/models/result.dart';
import '../../widgets/controls.dart';
import '../../widgets/icons.dart';
import '../../widgets/motion.dart';
import '../../app/theme/tokens.dart';

class FilterBar extends StatelessWidget {
  const FilterBar({super.key, this.onDone});

  /// After a choice: give the keyboard back to the search box.
  final VoidCallback? onDone;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final find = s.find;
    return ListenableBuilder(
      listenable: find,
      builder: (context, _) {
        final f = find.filters;
        void set(SearchFilters next) {
          find.setFilters(next);
          onDone?.call();
        }

        return AnimatedSize(
          duration: NbMotion.of(context, NbMotion.base),
          curve: NbMotion.curve,
          alignment: Alignment.topLeft,
          child: Wrap(
            spacing: 6,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              NbSelect(
                label: 'Kind',
                compact: true,
                value: f.kind,
                options: FilterChoices.kind,
                highlight: f.kind.isNotEmpty,
                onChanged: (v) => set(f.copyWith(kind: v)),
              ),
              NbSelect(
                label: 'Changed',
                compact: true,
                value: f.modified,
                options: FilterChoices.modified,
                highlight: f.modified.isNotEmpty,
                onChanged: (v) => set(f.copyWith(modified: v)),
              ),
              NbSelect(
                label: 'Size',
                compact: true,
                value: f.size,
                options: FilterChoices.size,
                highlight: f.size.isNotEmpty,
                onChanged: (v) => set(f.copyWith(size: v)),
              ),
              NbChipButton(
                f.folder.isEmpty ? 'Any folder' : 'In ${baseName(f.folder)}',
                icon: f.folder.isEmpty ? NbGlyph.folder : NbGlyph.close,
                on: f.folder.isNotEmpty,
                tooltip: f.folder.isEmpty ? 'Only inside one folder' : '${f.folder} (click to search everywhere again)',
                onTap: () async {
                  if (f.folder.isNotEmpty) return set(f.copyWith(folder: ''));
                  FolderPick p;
                  try {
                    p = await s.engine.pickFolder();
                  } on Object catch (e) {
                    return s.toasts.show(errorText(e));
                  }
                  if (p.busy) return s.toasts.show('The folder window is already open.');
                  if (p.path.isNotEmpty) set(find.filters.copyWith(folder: p.path));
                },
              ),
              if (find.here.isNotEmpty && f.folder != find.here)
                Appear(
                  key: ValueKey(find.here),
                  child: NbChipButton(
                    'Here: ${baseName(find.here)}',
                    tooltip: find.here,
                    onTap: () {
                      find.useHere();
                      onDone?.call();
                    },
                  ),
                ),
              NbSelect(
                label: 'Order',
                compact: true,
                value: f.sort,
                options: FilterChoices.sort,
                highlight: f.sort.isNotEmpty,
                onChanged: (v) => set(f.copyWith(sort: v)),
              ),
              if (!f.isEmpty)
                Appear(
                  key: const ValueKey('clear'),
                  child: NbChipButton(
                    'Clear filters',
                    dashed: true,
                    onTap: () {
                      find.clearFilters();
                      onDone?.call();
                    },
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}
