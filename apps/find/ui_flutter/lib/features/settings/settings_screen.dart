/// Settings: six pages (General, Indexing, Models, Performance, Privacy, About) under one sub-navigation; every
/// row and its wording is 0.7.0's (ui/app.js PAGES).
library;

import 'dart:async';

import 'package:flutter/widgets.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../widgets/panels.dart';
import '../../widgets/pressable.dart';
import 'pages/about.dart';
import 'pages/general.dart';
import 'pages/indexing.dart';
import 'pages/models.dart';
import 'pages/performance.dart';
import 'pages/privacy.dart';

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
    final c = NbColors.of(context);
    return ListenableBuilder(
      listenable: Listenable.merge([s.nav, s.settings, s.status]),
      builder: (context, _) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(NbSpace.x8, NbSpace.x6, NbSpace.x8, 0),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: c.line)),
            ),
            child: Align(
              alignment: Alignment.topLeft,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: NbSpace.column),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const PageTitle('Settings'),
                    const SizedBox(height: NbSpace.x5),
                    _SubNav(page: s.nav.page, onPick: s.nav.showPage),
                  ],
                ),
              ),
            ),
          ),
          Expanded(
            child: SingleChildScrollView(
              key: PageStorageKey(s.nav.page),
              padding: const EdgeInsets.fromLTRB(NbSpace.x8, NbSpace.x6, NbSpace.x8, NbSpace.x10),
              child: Align(
                alignment: Alignment.topLeft,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: NbSpace.column),
                  // not const: a page rebuilds when the settings or the status change. Without the engine the
                  // page says so and can't be changed (nothing would be saved).
                  child: _OfflineGate(
                    offline: !s.status.connected,
                    child: switch (s.nav.page) {
                      SettingsPage.general => GeneralPage(key: ValueKey(s.nav.page)),
                      SettingsPage.indexing => IndexingPage(key: ValueKey(s.nav.page)),
                      SettingsPage.models => ModelsPage(key: ValueKey(s.nav.page)),
                      SettingsPage.performance => PerformancePage(key: ValueKey(s.nav.page)),
                      SettingsPage.privacy => PrivacyPage(key: ValueKey(s.nav.page)),
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

class _SubNav extends StatelessWidget {
  const _SubNav({required this.page, required this.onPick});
  final SettingsPage page;
  final ValueChanged<SettingsPage> onPick;

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Semantics(
      label: 'Settings pages',
      container: true,
      child: Wrap(
        spacing: 4,
        children: [
          for (final p in SettingsPage.values)
            Pressable(
              onTap: () => onPick(p),
              selected: p == page,
              semanticLabel: p.label,
              builder: (context, st) => AnimatedContainer(
                duration: NbMotion.of(context, NbMotion.base),
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 9),
                decoration: BoxDecoration(
                  border: Border(bottom: BorderSide(color: p == page ? c.orange : const Color(0x00000000), width: 2)),
                ),
                child: Text(
                  p.label,
                  style: NbType.text(
                    13.5,
                    p == page ? c.orange : (st.lit ? c.text : c.dim),
                    weight: FontWeight.w600,
                    height: 1.2,
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
