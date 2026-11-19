/// Settings: eight pages, each a sidebar entry (General, Search, What to index, Models & languages, Performance,
/// Privacy & data, Shortcuts, About); the rows' wording is the 0.7.0 page's where 0.7.0 had them.
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../widgets/panels.dart';
import 'pages/about.dart';
import 'pages/general.dart';
import 'pages/indexing.dart';
import 'pages/models.dart';
import 'pages/performance.dart';
import 'pages/privacy.dart';
import 'pages/search.dart';
import 'pages/shortcuts.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  AppScope? _s;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final s = AppScope.of(context);
    if (_s != null) return; // once: the scope is rebuilt with the app, its controllers stay the same
    _s = s;
    unawaited(s.settings.load());
    unawaited(s.settings.loadExtras());
    unawaited(s.status.watch(true)); // model download states and the version come with status_full
  }

  @override
  void dispose() {
    unawaited(_s?.status.watch(false));
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    return ListenableBuilder(
      listenable: Listenable.merge([s.nav, s.settings, s.status]),
      builder: (context, _) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PageHeader(s.nav.page.label, crumb: 'Settings'),
          Expanded(
            child: SingleChildScrollView(
              key: PageStorageKey(s.nav.page),
              padding: const EdgeInsets.fromLTRB(NbSpace.gutter, 0, NbSpace.gutter, NbSpace.x6),
              // top-left at a reading width
              child: Align(
                alignment: Alignment.topLeft,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: NbSpace.column),
                  // not const: a page rebuilds when the settings or the status change. Without the engine the page
                  // says so and can't be changed (nothing would be saved).
                  child: _OfflineGate(
                    offline: !s.status.connected,
                    child: switch (s.nav.page) {
                      SettingsPage.general => GeneralPage(key: ValueKey(s.nav.page)),
                      SettingsPage.search => SearchSettingsPage(key: ValueKey(s.nav.page)),
                      SettingsPage.indexing => IndexingPage(key: ValueKey(s.nav.page)),
                      SettingsPage.models => ModelsPage(key: ValueKey(s.nav.page)),
                      SettingsPage.performance => PerformancePage(key: ValueKey(s.nav.page)),
                      SettingsPage.privacy => PrivacyPage(key: ValueKey(s.nav.page)),
                      SettingsPage.shortcuts => ShortcutsPage(key: ValueKey(s.nav.page)),
                      SettingsPage.about => AboutPage(key: ValueKey(s.nav.page)),
                    },
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Without the engine: a line saying so, and the page shown but not changeable.
class _OfflineGate extends StatelessWidget {
  const _OfflineGate({required this.offline, required this.child});
  final bool offline;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (!offline) return child;
    final c = NbColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: NbSpace.x5),
          child: Semantics(
            liveRegion: true,
            child: Text(
              "NOBAD Find's engine isn't running, so settings can't be changed right now. They come back with it.",
              style: NbType.text(13.5, c.warn, height: 1.5),
            ),
          ),
        ),
        IgnorePointer(
          child: ExcludeFocus(child: Opacity(opacity: .45, child: child)),
        ),
      ],
    );
  }
}
