/// Streaming Region Intelligence, "Where to watch" (the WebView's nobadvpn/ui/streamintel.js): which countries list a
/// movie, series or anime, on which platforms, documented restrictions, and which of your servers match. Everything
/// comes from TMDB/JustWatch, Wikipedia/Wikidata or the engine's own measurements (si_* methods and events); when a
/// source is missing or stale it says so. Connecting goes through the normal `connect`.
///
/// Posters: the WebView loaded them from the engine's HTTP image proxy; the pipe has no image route, so a neutral
/// tile with the title's first letter stands in for each poster and logo (no network fetch from this window).
library;

import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/scope.dart';
import '../../app/theme/colors.dart';
import '../../app/theme/tokens.dart';
import '../../app/theme/typography.dart';
import '../../engine/engine.dart';
import '../../engine/models.dart';
import '../../widgets/controls.dart';
import '../../widgets/dialogs.dart';
import '../../widgets/panels.dart';
import '../actions.dart';

const tmdbNotice = 'This product uses the TMDB API but is not endorsed or certified by TMDB.';
const watchAttribution = 'Streaming availability data provided by JustWatch (via TMDB).';
const _tmdbSignup = 'https://www.themoviedb.org/signup', _tmdbApi = 'https://www.themoviedb.org/settings/api';
const _offers = ['subscription', 'free', 'free with ads', 'rent', 'buy'];
const _panes = [('match', 'Best match'), ('countries', 'Countries'), ('platforms', 'Platforms'), ('restrictions', 'Restrictions'), ('sources', 'Sources')];

String _ago(Object? ts) {
  final t = jNum(ts);
  if (t == null || t == 0) return '—';
  final s = (DateTime.now().millisecondsSinceEpoch / 1000 - t).round().clamp(0, 1 << 31);
  return s < 90 ? 'just now' : (s < 5400 ? '${(s / 60).round()} min' : (s < 172800 ? '${(s / 3600).round()} h' : '${(s / 86400).round()} d'));
}

class StreamingScreen extends StatefulWidget {
  const StreamingScreen({super.key});
  @override
  State<StreamingScreen> createState() => _StreamingScreenState();
}

class _StreamingScreenState extends State<StreamingScreen> {
  Map<String, Object?>? _status;
  final _q = TextEditingController();
  final _cq = TextEditingController();
  List<Map<String, Object?>> _results = const [];
  final _recent = <String>[];
  String _query = '';
  bool _searching = false;
  String? _err;
  int _ticket = 0;

  // the title view
  String? _loading; // the key being loaded
  String? _titleErr;
  Map<String, Object?>? _rep, _restr, _rec, _verify;
  String _pane = 'match', _filter = 'all';
  int? _provider;
  ({String server, String cc, List<String> services, String stage, bool seen, DateTime t0})? _pending;
  StreamSubscription<EngineEvent>? _sub;
  AppNav? _nav;

  /// "Where to watch ..." from the command palette.
  void _asked() {
    if (!mounted) return;
    final q = AppScope.of(context).nav.takeAsk('watch');
    if (q == null) return;
    _q.text = q;
    _search(q);
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final scope = AppScope.of(context);
      _sub = scope.engine.events.listen(_event);
      scope.vpn.addListener(_onState);
      (_nav = scope.nav).addListener(_asked);
      _loadStatus();
      _asked();
    });
  }

  @override
  void dispose() {
    _nav?.removeListener(_asked);
    _sub?.cancel();
    try {
      AppScope.of(context).vpn.removeListener(_onState);
    } on Object {
      // already gone
    }
    _q.dispose();
    _cq.dispose();
    super.dispose();
  }

  Future<Answer?> _ask(String method, [Map<String, Object?> p = const {}]) async {
    try {
      return Answer.fromJson(await AppScope.of(context).engine.call(method, p));
    } on Object catch (e) {
      if (mounted) AppScope.of(context).vpn.toast(e is RpcException ? e.message : "NOBAD VPN isn't running. Start it from the Start menu.");
      return null;
    }
  }

  Future<void> _loadStatus() async {
    final a = await _ask('si_status');
    if (a != null && a.ok && mounted) setState(() => _status = a.data);
  }

  void _event(EngineEvent e) {
    if (!mounted) return;
    final p = e.map;
    switch (e.name) {
      case 'si_title':
        if (p['key'] != _loading) return;
        setState(() {
          if (!jBool(p['ok'])) {
            _titleErr = jStr(p['error'], "Couldn't load this title");
          } else {
            _rep = p;
            _rec = null;
          }
        });
      case 'si_restrictions':
        if (_rep == null || p['key'] != _rep!['key']) return;
        setState(() {
          _restr = jMap(p['restrictions']);
          _rec = p['recommendation'] is Map ? jMap(p['recommendation']) : null;
        });
      case 'si_verify':
        setState(() {
          _verify = p;
          _pending = null;
        });
      case 'task_done':
        final m = RegExp(r'^si_title:(.+)$').firstMatch(jStr(p['key']));
        final err = jStrN(p['error']);
        setState(() {
          if (m != null && m[1] == _loading && (_rep == null || _rep!['key'] != m[1]) && err != null) _titleErr = err;
          if (m != null && _rep != null && _rep!['key'] == m[1] && _restr == null) {
            _restr = {'status': 'unavailable', 'records': <Object?>[], 'note': 'The restriction lookup stopped.'};
          }
          if (p['key'] == 'si_verify' && _pending?.stage == 'verify') _pending = null;
        });
    }
  }

  /// After Connect: once the server is up, check the exit country and the platforms (si_verify).
  void _onState() {
    final p = _pending;
    final st = AppScope.of(context).vpn.state;
    if (p == null || p.stage != 'connect' || st == null) return;
    if (st.connected && st.active == p.server) {
      setState(() => _pending = (server: p.server, cc: p.cc, services: p.services, stage: 'verify', seen: p.seen, t0: p.t0));
      _ask('si_verify', {'country': p.cc, 'services': p.services});
    } else if (st.connecting != null) {
      _pending = (server: p.server, cc: p.cc, services: p.services, stage: p.stage, seen: true, t0: p.t0);
    } else if ((st.error?.name == p.server) || (p.seen && !st.connected) || DateTime.now().difference(p.t0).inSeconds > 90) {
      setState(() => _pending = null);
      AppScope.of(context).vpn.toast("Couldn't connect to ${p.server}");
    }
  }

  Future<void> _search([String? text]) async {
    final q = (text ?? _q.text).trim();
    if (q.length < 2) {
      AppScope.of(context).vpn.toast('Type at least two characters.');
      return;
    }
    _q.text = q;
    final ticket = ++_ticket;
    setState(() {
      _query = q;
      _err = null;
      _searching = true;
      _rep = null;
      _loading = null;
      _titleErr = null;
    });
    final a = await _ask('si_search', {'q': q});
    if (!mounted || ticket != _ticket) return; // a newer search started meanwhile
    setState(() {
      _searching = false;
      if (a == null || !a.ok) {
        _err = a?.error;
        _results = const [];
        if (a?.data['code'] == 'no-key') _loadStatus();
      } else {
        _results = [for (final r in jList(a.data['results'])) jMap(r)];
        _recent.removeWhere((x) => x.toLowerCase() == q.toLowerCase());
        _recent.insert(0, q);
        if (_recent.length > 5) _recent.removeRange(5, _recent.length);
      }
    });
  }

  Future<void> _openTitle(String key, {bool force = false}) async {
    setState(() {
      _rep = _restr = _rec = _verify = null;
      _titleErr = null;
      _filter = 'all';
      _provider = null;
      _cq.clear();
      _loading = key;
    });
    final a = await _ask('si_title', {'key': key, if (force) 'force': true});
    if (a != null && !a.ok && mounted) setState(() => _titleErr = a.error);
  }

  Future<void> openLink(String? url) async {
    final vpn = AppScope.of(context).vpn;
    if (url == null || url.isEmpty) {
      vpn.toast('This item has no link');
      return;
    }
    final a = await _ask('si_open', {'url': url});
    if (a == null || !mounted) return;
    if (a.ok) {
      vpn.toast('Opening in your browser…', good: true);
    } else if (a.error == 'confirm') {
      final ok = await confirmDialog(context,
          title: 'Open link', question: 'Open this link in your browser?\n${jStr(a.data['host'])}', yes: 'Open');
      if (!ok) return;
      final b = await _ask('si_open', {'url': url, 'confirm': true});
      if (b != null) b.ok ? vpn.toast('Opening in your browser…', good: true) : vpn.toast(b.error);
    } else {
      vpn.toast(a.error.isEmpty ? "Couldn't open that link" : a.error);
    }
  }

  Future<void> _connect(String server, String cc, List<String> services) async {
    final vpn = AppScope.of(context).vpn;
    final st = vpn.state;
    if (st != null && st.connected && st.active == server) {
      setState(() => _pending = (server: server, cc: cc, services: services, stage: 'verify', seen: false, t0: DateTime.now()));
      await _ask('si_verify', {'country': cc, 'services': services});
      return;
    }
    setState(() {
      _pending = (server: server, cc: cc, services: services, stage: 'connect', seen: false, t0: DateTime.now());
      _verify = null;
    });
    final a = await _ask('connect', {'name': server});
    if (a != null && !a.ok && mounted) {
      setState(() => _pending = null);
      vpn.toast(a.error.isEmpty ? 'Could not connect' : a.error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(NbSpace.x3),
      child: Align(
        alignment: Alignment.topLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const PageTitle('Streaming',
                  sub: 'Find which countries list a movie, series or anime, on which platforms, and which of your servers match.'),
              const SizedBox(height: NbSpace.x3),
              _searchCard(c),
              const SizedBox(height: NbSpace.x3),
              if (_loading != null) _titleView(c) else _resultsView(c),
              const SizedBox(height: NbSpace.x3),
              _attribution(c),
            ],
          ),
        ),
      ),
    );
  }

  Widget _searchCard(NbColors c) {
    final st = _status;
    final basic = st != null && !jBool(st['configured']);
    return NbPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Where to watch', style: NbType.label(NbSize.lead, c.text)),
              const SizedBox(height: 4),
              Text('Find which countries list a movie, series or anime, on which platforms, and which of your servers match.',
                  style: NbType.text(NbSize.small, c.muted, height: 1.45)),
            ]),
          ),
          NbButton('Data sources', small: true, kind: NbButtonKind.ghost, onPressed: _setup),
        ]),
        const SizedBox(height: NbSpace.x3),
        Row(children: [
          Expanded(
            child: Semantics(
              label: 'Search titles',
              child: NbTextBox(controller: _q, label: '', hint: 'Movie, series or anime…', maxLength: 200, onSubmitted: (_) => _search()),
            ),
          ),
          const SizedBox(width: NbSpace.x2),
          NbButton('Search', onPressed: _searching ? null : _search),
        ]),
        if (basic) ...[
          const SizedBox(height: NbSpace.x2),
          Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
            const _Tag('Works without setup'),
            Text('Platforms and restrictions from Wikidata and Wikipedia.', style: NbType.text(NbSize.small, c.muted)),
            NbButton('Add a free TMDB key for country-by-country availability', small: true, kind: NbButtonKind.quiet, onPressed: _setup),
          ]),
        ],
        if (_recent.isNotEmpty) ...[
          const SizedBox(height: NbSpace.x2),
          Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
            Text('Recent:', style: NbType.text(NbSize.small, c.muted)),
            for (final q in _recent) NbChipButton(q, onTap: () => _search(q)),
          ]),
        ],
      ]),
    );
  }

  Widget _resultsView(NbColors c) {
    if (_searching) return const _Busy('Searching…');
    if (_err != null) return Notice(kind: NoticeKind.warn, title: _err!);
    if (_results.isEmpty) {
      return _query.isEmpty
          ? const SizedBox.shrink()
          : const _Empty('No matching titles. Try the original title, add a year (Dune 2021) or paste an IMDb link.');
    }
    final inferred = _results.any((r) => jBool(jMap(r['type'])['inferred']));
    return NbPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('${_results.length} ${_results.length == 1 ? 'result' : 'results'} for “$_query”', style: NbType.text(NbSize.small, c.muted)),
        const SizedBox(height: NbSpace.x2),
        Wrap(spacing: NbSpace.x2, runSpacing: NbSpace.x2, children: [
          for (final r in _results)
            _TitleTile(
              title: jStr(r['title']),
              sub: [if (r['year'] != null) '${r['year']}', '${jStr(jMap(r['type'])['label'])}${jBool(jMap(r['type'])['inferred']) ? '*' : ''}'].join(' · '),
              original: jStrN(r['original_title']),
              onTap: () => _openTitle(jStr(r['key'])),
            ),
        ]),
        if (inferred)
          Padding(
            padding: const EdgeInsets.only(top: NbSpace.x2),
            child: Text('* Anime is inferred from Japanese-language animation.', style: NbType.text(NbSize.small, c.muted)),
          ),
      ]),
    );
  }

  Widget _titleView(NbColors c) {
    final back = _results.isNotEmpty
        ? Align(
            alignment: Alignment.centerLeft,
            child: NbButton('← Results', small: true, kind: NbButtonKind.quiet, onPressed: () => setState(() => _loading = null)),
          )
        : const SizedBox.shrink();
    if (_titleErr != null) {
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        back,
        Notice(
          kind: NoticeKind.warn,
          title: "Couldn't load this title",
          detail: _titleErr!,
          actions: [NoticeAction('Try again', () => _openTitle(_loading!, force: true))],
        ),
      ]);
    }
    final r = _rep;
    if (r == null) return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [back, const _Busy('Reading catalogues and your servers…')]);
    final t = jMap(r['title']);
    final basic = r['mode'] == 'basic';
    final ids = jMap(t['ids']);
    final type = jMap(t['type']);
    final meta = <String>[
      '${jStr(type['label'])}${jBool(type['inferred']) && !basic ? '*' : ''}',
      if (!basic) [for (final g in jList(t['genres']).take(3)) '$g'].join(', '),
      if (basic && t['year'] != null) '${t['year']}',
      if (jInt(t['seasons']) > 0) '${jInt(t['seasons'])} ${jInt(t['seasons']) == 1 ? 'season' : 'seasons'}' else if (jInt(t['runtime']) > 0) '${jInt(t['runtime'])} min',
      if (!basic && jStrN(t['status']) != null) jStr(t['status']),
    ].where((x) => x.isNotEmpty).toList();
    final links = <(String, String)>[
      if (jStrN(ids['imdb']) != null) ('IMDb', 'https://www.imdb.com/title/${ids['imdb']}/'),
      if (jStrN(t['tmdb_url']) != null) ('TMDB', jStr(t['tmdb_url'])),
      if (basic && jStrN(ids['wikidata']) != null) ('Wikidata', 'https://www.wikidata.org/wiki/${ids['wikidata']}'),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      back,
      NbPanel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _Poster(letter: jStr(t['title'], '?')),
            const SizedBox(width: NbSpace.x3),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${jStr(t['title'])}${t['year'] != null ? ' (${t['year']})' : ''}', style: NbType.label(NbSize.lead, c.text)),
                if (jStrN(t['original_title']) != null)
                  Text('Original title: ${jStr(t['original_title'])}', style: NbType.text(NbSize.small, c.muted)),
                const SizedBox(height: 6),
                Wrap(spacing: 6, runSpacing: 4, children: [for (final m in meta) _Tag(m)]),
                const SizedBox(height: 6),
                Text(jStr(t['overview'], basic ? '' : 'No description on TMDB.'), style: NbType.text(NbSize.small, c.muted, height: 1.45)),
                const SizedBox(height: 6),
                Wrap(spacing: 6, children: [
                  for (final (n, u) in links) NbButton(n, small: true, kind: NbButtonKind.ghost, onPressed: () => openLink(u)),
                ]),
              ]),
            ),
          ]),
          if (!basic && jList(t['alternative_titles']).isNotEmpty) ...[
            const SizedBox(height: NbSpace.x2),
            Text('Also known as (${jList(t['alternative_titles']).length})', style: NbType.label(NbSize.small, c.text)),
            Wrap(spacing: 6, runSpacing: 4, children: [
              for (final a in jList(t['alternative_titles']).take(30).map(jMap))
                _Tag('${jStr(a['title'])}${jStrN(a['country']) != null ? ' · ${a['country']}' : ''}'),
            ]),
          ],
        ]),
      ),
      const SizedBox(height: NbSpace.x3),
      if (basic) _basicBody(c, r) else ...[
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final (k, n) in _panes)
            NbChipButton(
              k == 'restrictions' && _restr != null && _restr!['status'] == 'ok' && jList(_restr!['records']).isNotEmpty
                  ? '$n ${jList(_restr!['records']).length}'
                  : n,
              on: _pane == k,
              onTap: () => setState(() => _pane = k),
            ),
        ]),
        const SizedBox(height: NbSpace.x3),
        NbPanel(
          child: switch (_pane) {
            'countries' => _countries(c),
            'platforms' => _platforms(c),
            'restrictions' => _restrictions(c),
            'sources' => _sources(c),
            _ => _match(c),
          },
        ),
      ],
    ]);
  }

  Widget _basicBody(NbColors c, Map<String, Object?> r) {
    final plats = [for (final p in jList(r['platforms'])) jMap(p)];
    return NbPanel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _restrSummary(c, compact: false) ?? (_restr == null ? const _Busy('Checking documented restrictions…') : const SizedBox.shrink()),
        const _Sub('Streams on'),
        if (plats.isEmpty)
          const _Empty('No streaming platform is recorded for this title on Wikidata yet.')
        else ...[
          Wrap(spacing: NbSpace.x2, runSpacing: NbSpace.x2, children: [
            for (final p in plats)
              _PlatformTile(name: jStr(p['name']), sub: 'Open on ${jStr(p['name'])} ↗', onTap: () => openLink(jStrN(p['url']))),
          ]),
          const SizedBox(height: NbSpace.x2),
          Text(
            "Platforms list titles per country, so it may not be in the catalogue where you are. Connect to a server in the "
            "platform's main country (often the US) if it isn't.",
            style: NbType.text(NbSize.small, c.muted, height: 1.45),
          ),
        ],
        const SizedBox(height: NbSpace.x2),
        Wrap(spacing: 6, runSpacing: 6, children: [
          NbButton('See countries on JustWatch ↗', small: true, kind: NbButtonKind.ghost, onPressed: () => openLink(jStrN(r['justwatch_url']))),
          NbButton('Per-country view in NOBAD (free TMDB key)', small: true, kind: NbButtonKind.ghost, onPressed: _setup),
        ]),
        const _Sub('Restrictions'),
        _restrictions(c),
      ]),
    );
  }

  /// Countries with a documented ban/restriction record for this exact title, by ISO code.
  Map<String, List<Map<String, Object?>>> _restricted() {
    final d = _restr;
    if (d == null || d['status'] != 'ok') return const {};
    final out = <String, List<Map<String, Object?>>>{};
    for (final r in jList(d['records']).map(jMap)) {
      out.putIfAbsent(jStr(r['code'], jStr(r['country'], '?')), () => []).add(r);
    }
    return out;
  }

  Widget? _restrSummary(NbColors c, {required bool compact}) {
    final d = _restr;
    if (d == null || d['status'] != 'ok' || jList(d['records']).isEmpty) return null;
    final by = _restricted();
    final tags = {for (final r in jList(d['records']).map(jMap)) ...jList(r['tags']).map((x) => '$x')}.take(4);
    return Container(
      margin: const EdgeInsets.only(bottom: NbSpace.x2),
      padding: const EdgeInsets.all(NbSpace.x3),
      decoration: BoxDecoration(borderRadius: NbRadius.rowAll, border: Border.all(color: c.blocked.withValues(alpha: .5))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('Banned / restricted', style: NbType.label(NbSize.small, c.blocked)),
          const SizedBox(width: 8),
          Text('in ${by.length} ${by.length == 1 ? 'country' : 'countries'}', style: NbType.label(NbSize.body, c.text)),
        ]),
        const SizedBox(height: 6),
        Wrap(spacing: 4, runSpacing: 4, children: [
          for (final e in by.entries.take(30))
            Tooltip(
              message: jStr(e.value.first['country_name'], jStr(e.value.first['country'], e.key)),
              child: _Cc(e.key.length <= 3 ? e.key : jStr(e.value.first['country_name'], e.key), tone: c.blocked),
            ),
        ]),
        if (tags.isNotEmpty) ...[const SizedBox(height: 6), Wrap(spacing: 4, children: [for (final t in tags) _Tag(t)])],
        const SizedBox(height: 6),
        if (compact)
          NbButton('See the records and sources →', small: true, kind: NbButtonKind.quiet, onPressed: () => setState(() => _pane = 'restrictions'))
        else
          Text("Documented in Wikipedia's banned-film lists with their sources. A ban may be historic and lifted since; check "
              'the date and notes.', style: NbType.text(NbSize.small, c.muted, height: 1.45)),
      ]),
    );
  }

  Widget _match(NbColors c) {
    final r = _rep!;
    final rec = _rec ?? jMap(r['recommendation']);
    final av = jMap(r['availability']);
    final kids = <Widget>[?_restrSummary(c, compact: true)];
    final home = jMap(rec['home']);
    if (home.isNotEmpty) {
      kids.add(jBool(home['listed'])
          ? Notice(kind: NoticeKind.info, title: 'Listed where you are (${jStr(home['code'])}) · ${jStr(home['best'])}',
              detail: 'You may not need a VPN for this one. See Countries for the platforms.')
          : Notice(kind: NoticeKind.info, title: 'Not listed in your country (${jStr(home['code'])})',
              detail: 'Based on the availability source; catalogues change often.'));
    }
    if (rec['verdict'] == 'not-listed-anywhere') {
      kids.add(const Notice(kind: NoticeKind.warn, title: 'No streaming listing found in any covered country',
          detail: "It may be in cinemas, unreleased, or simply not in the source's data yet. That isn't the same as unavailable everywhere."));
    } else if (rec['verdict'] == 'no-matching-server') {
      kids.add(Notice(kind: NoticeKind.warn,
          title: 'Listed in ${jList(av['listed']).length} countries, but none of your servers are in them',
          detail: 'Add a config for one of the countries below, or check servers whose country is unknown.'));
    }
    if (_restr == null) kids.add(const _Busy('Checking documented restrictions…'));
    final opts = [for (final o in jList(rec['options'])) jMap(o)];
    for (var i = 0; i < opts.length; i++) {
      final o = opts[i];
      final best = i == 0 && !jBool(o['restricted']);
      final others = jList(o['other_servers']).length;
      kids.add(Container(
        margin: const EdgeInsets.only(top: NbSpace.x2),
        padding: const EdgeInsets.all(NbSpace.x3),
        decoration: BoxDecoration(
          color: c.card,
          borderRadius: NbRadius.rowAll,
          border: Border.all(color: best ? c.orangeA(.6) : (jBool(o['restricted']) ? c.blocked.withValues(alpha: .5) : c.line)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            _Cc(jStr(o['code'])),
            const SizedBox(width: 8),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(jStr(o['name']), style: NbType.label(NbSize.body, c.text)),
                Text('via ${jStr(o['server'])}${others > 0 ? ' +$others' : ''}', style: NbType.text(NbSize.small, c.muted)),
              ]),
            ),
            _Tag(jStr(o['offer'])),
            const SizedBox(width: 8),
            Tooltip(message: 'Match score', child: Text('${jInt(o['score'])}', style: NbType.data(NbSize.body, c.text))),
          ]),
          const SizedBox(height: 6),
          for (final x in jList(o['reasons'])) Text('✓ $x', style: NbType.text(NbSize.small, c.sealed, height: 1.45)),
          for (final x in jList(o['caveats'])) Text('! $x', style: NbType.text(NbSize.small, c.amber, height: 1.45)),
          if (!jBool(o['restricted'])) ...[
            const SizedBox(height: 6),
            Align(
              alignment: Alignment.centerLeft,
              child: NbButton('Connect to ${jStr(o['server'])}', small: true, kind: i == 0 ? NbButtonKind.primary : NbButtonKind.ghost,
                  onPressed: () => _connect(jStr(o['server']), jStr(o['code']), [for (final s in jList(o['verify_services'])) '$s'])),
            ),
          ],
          _verifyBox(c, o),
        ]),
      ));
    }
    final without = jList(rec['listed_without_server']).map(jMap).toList();
    if (without.isNotEmpty) {
      kids.add(const _Sub('Also listed where you have no server'));
      kids.add(Wrap(spacing: 4, runSpacing: 4, children: [
        for (final x in without.take(60)) Tooltip(message: '${jStr(x['name'])} · ${jStr(x['best'])}', child: _Cc(jStr(x['code']))),
      ]));
    }
    final unknown = [for (final s in jList(rec['servers_unknown'])) '$s'];
    if (unknown.isNotEmpty) {
      kids.add(Padding(
        padding: const EdgeInsets.only(top: NbSpace.x2),
        child: Text('Servers with an unknown country (not matched): ${unknown.join(', ')}. Turn on IP lookup in Settings → Privacy to locate them.',
            style: NbType.text(NbSize.small, c.muted, height: 1.45)),
      ));
    }
    if (jStrN(rec['disclaimer']) != null) {
      kids.add(Padding(
        padding: const EdgeInsets.only(top: NbSpace.x2),
        child: Text(jStr(rec['disclaimer']), style: NbType.text(NbSize.caption, c.dim, height: 1.45)),
      ));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: kids);
  }

  Widget _verifyBox(NbColors c, Map<String, Object?> o) {
    final v = _verify;
    final server = jStr(o['server']);
    if (v != null && v['server'] == server && jStrN(v['error']) != null) {
      return Padding(padding: const EdgeInsets.only(top: 6), child: Notice(kind: NoticeKind.warn, title: jStr(v['error'])));
    }
    if (_pending?.server == server) {
      return _Busy(_pending!.stage == 'verify' ? 'Checking the exit and platforms…' : 'Connecting…');
    }
    if (v == null || v['server'] != server) return const SizedBox.shrink();
    final cm = v['country_match'];
    final lines = <(bool, String)>[
      if (cm == true)
        (true, 'Exit address is in ${jStr(v['exit_country'])}')
      else if (cm == false)
        (false, 'Exit address is in ${jStr(v['exit_country'])}, not ${jStr(v['country'])}')
      else
        (false, v['exit_lookup'] == 'disabled' ? 'Exit country not checked: IP lookup is off' : "Exit country couldn't be checked"),
      for (final s in jList(v['services']).map(jMap)) (s['level'] == 'ok', '${jStr(s['name'])}: ${jStr(s['note'])}'),
    ];
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final (ok, t) in lines) Text('${ok ? '✓' : '!'} $t', style: NbType.text(NbSize.small, ok ? c.sealed : c.amber, height: 1.45)),
        Text("Reachable means the site answered from this exit. It doesn't guarantee a particular title will play.",
            style: NbType.text(NbSize.caption, c.dim, height: 1.45)),
      ]),
    );
  }

  Map<String, Object?> _prov(Object? id) =>
      jList(jMap(_rep!['availability'])['providers']).map(jMap).where((p) => p['id'] == id).firstOrNull ?? {'name': '#$id'};

  Widget _countries(NbColors c) {
    final av = jMap(_rep!['availability']);
    final listed = jList(av['listed']).map(jMap).toList();
    final mine = {for (final s in jList(_rep!['servers']).map(jMap)) if (jStrN(s['country']) != null) jStr(s['country'])};
    final ban = _restricted();
    final q = _cq.text.trim().toLowerCase();
    bool hasOffer(Map<String, Object?> ctry, String t) => jList(jMap(ctry['offers'])[t]).isNotEmpty;
    final rows = listed.where((ctry) {
      if (_filter != 'all' && !hasOffer(ctry, _filter)) return false;
      if (_provider != null && !jMap(ctry['offers']).values.any((l) => jList(l).contains(_provider))) return false;
      return q.isEmpty || jStr(ctry['name']).toLowerCase().contains(q) || jStr(ctry['code']).toLowerCase() == q;
    }).toList();
    final counts = {for (final t in _offers) t: listed.where((ctry) => hasOffer(ctry, t)).length};
    final notListed = jList(av['not_listed']).map(jMap).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
        NbChipButton('All ${listed.length}', on: _filter == 'all', onTap: () => setState(() => _filter = 'all')),
        for (final t in _offers.where((t) => counts[t]! > 0))
          NbChipButton('$t ${counts[t]}', on: _filter == t, onTap: () => setState(() => _filter = t)),
        SizedBox(
          width: 200,
          child: Semantics(
            label: 'Find a country',
            child: NbTextBox(controller: _cq, label: '', hint: 'Find a country', maxLength: 60, onChanged: (_) => setState(() {})),
          ),
        ),
      ]),
      if (_provider != null)
        Row(children: [
          Text('Only ${jStr(_prov(_provider)['name'])} · ', style: NbType.text(NbSize.small, c.muted)),
          NbButton('show all platforms', small: true, kind: NbButtonKind.quiet, onPressed: () => setState(() => _provider = null)),
        ]),
      const SizedBox(height: NbSpace.x2),
      if (rows.isEmpty)
        const _Empty('No listed countries match.')
      else
        for (final ctry in rows)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 6),
            decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.line))),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _Cc(jStr(ctry['code'])),
              const SizedBox(width: 8),
              SizedBox(
                width: 170,
                child: Wrap(spacing: 6, runSpacing: 2, children: [
                  Text(jStr(ctry['name']), style: NbType.label(NbSize.small, c.text)),
                  if (mine.contains(ctry['code'])) Text('your server', style: NbType.text(NbSize.caption, c.orange)),
                  if (ban.containsKey(ctry['code']))
                    Tooltip(message: 'Documented ban or restriction: see Restrictions',
                        child: Text('restricted', style: NbType.text(NbSize.caption, c.blocked))),
                ]),
              ),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final t in _offers.where((t) => hasOffer(ctry, t)))
                    Text('$t: ${[for (final id in jList(jMap(ctry['offers'])[t])) jStr(_prov(id)['name'])].join(', ')}',
                        style: NbType.text(NbSize.small, c.muted, height: 1.4)),
                ]),
              ),
              if (jStrN(ctry['link']) != null)
                Tooltip(
                  message: 'Watch options on TMDB (JustWatch data)',
                  child: NbButton('↗', small: true, kind: NbButtonKind.quiet, onPressed: () => openLink(jStr(ctry['link']))),
                ),
            ]),
          ),
      if (notListed.isNotEmpty) ...[
        _Sub('Not listed in ${notListed.length} covered countries'),
        Wrap(spacing: 4, runSpacing: 4, children: [
          for (final x in notListed) Tooltip(message: jStr(x['name']), child: _Cc(jStr(x['code']), tone: c.dim)),
        ]),
      ],
      Padding(
        padding: const EdgeInsets.only(top: NbSpace.x2),
        child: Text(
          '${jBool(av['coverage_known']) ? jStr(av['unknown_note']) : "The list of countries the source covers couldn't be loaded, so unlisted countries are shown as unknown."} '
          'Coverage: ${av['coverage'] ?? '—'} countries.',
          style: NbType.text(NbSize.small, c.muted, height: 1.45),
        ),
      ),
    ]);
  }

  Widget _platforms(NbColors c) {
    final provs = jList(jMap(_rep!['availability'])['providers']).map(jMap).toList();
    if (provs.isEmpty) return const _Empty('No platforms list this title in any covered country.');
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Wrap(spacing: NbSpace.x2, runSpacing: NbSpace.x2, children: [
        for (final p in provs)
          _PlatformTile(
            name: jStr(p['name']),
            sub: '${jMap(p['countries']).length} countries · ${{for (final l in jMap(p['countries']).values) ...jList(l).map((x) => '$x')}.join(', ')}',
            onTap: () => setState(() {
              _provider = jInt(p['id']);
              _pane = 'countries';
            }),
          ),
      ]),
      const SizedBox(height: NbSpace.x2),
      Text('Select a platform to see its countries.', style: NbType.text(NbSize.small, c.muted)),
    ]);
  }

  Widget _restrictions(NbColors c) {
    final d = _restr;
    final certs = jList(_rep?['certifications']).map(jMap).toList();
    final kids = <Widget>[
      Text('Documented legal or censorship restrictions are kept separate from streaming licensing. A title missing from a '
          'catalogue is not a ban.', style: NbType.text(NbSize.small, c.muted, height: 1.45)),
      const SizedBox(height: NbSpace.x2),
    ];
    if (d == null) {
      kids.add(const _Busy('Loading restriction records…'));
    } else if (d['status'] != 'ok') {
      kids.add(Notice(
        kind: d['status'] == 'unavailable' ? NoticeKind.warn : NoticeKind.info,
        title: d['status'] == 'unavailable' ? 'Restriction records unavailable' : 'No matchable restriction records',
        detail: jStr(d['note']),
      ));
    } else if (jList(d['records']).isEmpty) {
      kids.add(const Notice(kind: NoticeKind.info, title: 'No documented bans or blocks found',
          detail: "Checked Wikipedia's banned-film lists for this exact title. Absence from these lists doesn't prove there were no restrictions."));
    } else {
      kids.add(_restrSummary(c, compact: false)!);
      for (final r in jList(d['records']).map(jMap)) {
        final srcs = jList(r['sources']).map(jMap).toList();
        kids.add(Container(
          margin: const EdgeInsets.only(top: NbSpace.x2),
          padding: const EdgeInsets.all(NbSpace.x3),
          decoration: BoxDecoration(color: c.card, borderRadius: NbRadius.rowAll, border: Border.all(color: c.line)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              _Cc(jStr(r['code'], '—')),
              const SizedBox(width: 8),
              Expanded(child: Text(jStr(r['country_name'], jStr(r['country'], 'Unknown country')), style: NbType.label(NbSize.body, c.text))),
              Text(jStr(r['date'], 'date not given'), style: NbType.data(NbSize.caption, c.muted)),
            ]),
            const SizedBox(height: 4),
            Text(jStr(r['notes'], 'No details in the list.'), style: NbType.text(NbSize.small, c.muted, height: 1.45)),
            if (jList(r['tags']).isNotEmpty) ...[
              const SizedBox(height: 4),
              Wrap(spacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                for (final t in jList(r['tags'])) _Tag('$t'),
                Text('from the notes', style: NbType.text(NbSize.caption, c.dim)),
              ]),
            ],
            const SizedBox(height: 4),
            Wrap(spacing: 6, runSpacing: 2, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text(jStr(r['verification']), style: NbType.text(NbSize.caption, c.muted)),
              for (final s in srcs)
                jStrN(s['url']) != null
                    ? NbButton(jStr(s['title'], jStr(s['publisher'], Uri.tryParse(jStr(s['url']))?.host ?? jStr(s['url']))), small: true,
                        kind: NbButtonKind.quiet, onPressed: () => openLink(jStr(s['url'])))
                    : Text(jStr(s['title'], jStr(s['text'])), style: NbType.text(NbSize.caption, c.muted)),
              NbButton('Wikipedia section', small: true, kind: NbButtonKind.quiet, onPressed: () => openLink(jStrN(r['url']))),
            ]),
          ]),
        ));
      }
    }
    if (certs.isNotEmpty) {
      kids.add(const _Sub('Age ratings'));
      kids.add(Text('TMDB, from national rating boards', style: NbType.text(NbSize.caption, c.dim)));
      kids.add(Wrap(spacing: 6, runSpacing: 4, children: [
        for (final x in certs) Tooltip(message: jStr(x['name'], jStr(x['country'])), child: _Tag('${jStr(x['country'])} ${jStr(x['rating'])}')),
      ]));
    }
    kids.add(Padding(
      padding: const EdgeInsets.only(top: NbSpace.x2),
      child: Text("Connecting to another region doesn't change which laws apply to you, and NOBAD doesn't help bypass legal restrictions.",
          style: NbType.text(NbSize.caption, c.dim, height: 1.45)),
    ));
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: kids);
  }

  Widget _sources(NbColors c) {
    final r = _rep!;
    final av = jMap(r['availability']);
    final d = _restr;
    final ids = jMap(jMap(r['title'])['ids']);
    final servers = jList(r['servers']).map(jMap).toList();
    Widget row(String k, String v) => Container(
      padding: const EdgeInsets.symmetric(vertical: 6),
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: c.line))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 180, child: Text(k, style: NbType.text(NbSize.small, c.muted))),
        Expanded(child: Text(v, style: NbType.text(NbSize.small, c.text))),
      ]),
    );
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      row('Titles and metadata', 'TMDB'),
      row('Streaming availability', 'JustWatch via TMDB · ${_ago(av['fetched'])} ago · ${jBool(av['fresh']) ? 'fresh' : 'stale'}'),
      row('Restrictions', d == null ? 'loading' : (d['status'] == 'ok' ? 'Wikipedia (${d['pages']} lists) · index ${_ago(d['index_built'])} ago' : jStr(d['status']))),
      row('Identity', [
        'TMDB ${ids['tmdb'] ?? '—'}',
        if (jStrN(ids['imdb']) != null) 'IMDb ${ids['imdb']}',
        if (jStrN(ids['wikidata']) != null) 'Wikidata ${ids['wikidata']}',
      ].join(' · ')),
      row('Your servers',
          '${servers.length} (${servers.where((s) => s['country_basis'] == 'ip-geolocation').length} located by IP, '
              '${servers.where((s) => s['country_basis'] == 'name').length} by name)'),
      const SizedBox(height: NbSpace.x2),
      Align(
        alignment: Alignment.centerLeft,
        child: NbButton('Refresh now', small: true, kind: NbButtonKind.ghost, onPressed: () => _openTitle(jStr(r['key']), force: true)),
      ),
      if (jStrN(_status?['restrictions_license']) != null)
        Padding(
          padding: const EdgeInsets.only(top: NbSpace.x2),
          child: Text(jStr(_status!['restrictions_license']), style: NbType.text(NbSize.caption, c.dim)),
        ),
    ]);
  }

  Widget _attribution(NbColors c) => Semantics(
    container: true,
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(jStr(_status?['notice'], tmdbNotice), style: NbType.text(NbSize.caption, c.dim)),
      Text(jStr(_status?['watch_attribution'], watchAttribution), style: NbType.text(NbSize.caption, c.dim)),
    ]),
  );

  /// Data sources: the TMDB key, the services you have, the cache.
  Future<void> _setup() => showScoped<void>(context, (ctx) => _SetupDialog(status: _status, onChanged: _loadStatus, openLink: openLink));
}

class _SetupDialog extends StatefulWidget {
  const _SetupDialog({required this.status, required this.onChanged, required this.openLink});
  final Map<String, Object?>? status;
  final Future<void> Function() onChanged;
  final Future<void> Function(String?) openLink;
  @override
  State<_SetupDialog> createState() => _SetupDialogState();
}

class _SetupDialogState extends State<_SetupDialog> {
  final _key = TextEditingController();
  late final _region = TextEditingController(text: jStr(AppScope.of(context).vpn.state?.home['country']));
  String _msg = '';
  bool _saving = false;
  List<Map<String, Object?>>? _providers;
  String? _provErr;
  late Set<int> _mine = {for (final x in jList(widget.status?['my_services'])) if (x is int) x};
  late Map<String, Object?>? _st = widget.status;

  @override
  void initState() {
    super.initState();
    if (jBool(_st?['configured'])) WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _key.dispose();
    _region.dispose();
    super.dispose();
  }

  Future<Answer?> _ask(String m, [Map<String, Object?> p = const {}]) async {
    try {
      return Answer.fromJson(await AppScope.of(context).engine.call(m, p));
    } on Object {
      return null;
    }
  }

  Future<void> _refresh() async {
    await widget.onChanged();
    final a = await _ask('si_status');
    if (a != null && a.ok && mounted) {
      setState(() {
        _st = a.data;
        _mine = {for (final x in jList(a.data['my_services'])) if (x is int) x};
      });
    }
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _msg = 'Checking with TMDB…';
    });
    final a = await _ask('si_key', {'key': _key.text.trim()});
    if (!mounted) return;
    setState(() {
      _saving = false;
      _msg = a == null ? "NOBAD VPN isn't running." : (a.ok ? 'Saved. You can search now.' : a.error);
    });
    if (a != null && a.ok) {
      _key.clear();
      await _refresh();
    }
  }

  Future<void> _load() async {
    setState(() {
      _providers = null;
      _provErr = null;
    });
    final a = await _ask('si_providers', {'region': _region.text.trim().toUpperCase()});
    if (!mounted) return;
    setState(() {
      if (a == null || !a.ok) {
        _provErr = a?.error ?? "NOBAD VPN isn't running.";
        _providers = const [];
      } else {
        _providers = [for (final p in jList(a.data['providers']).take(120)) jMap(p)];
      }
    });
  }

  Future<void> _toggle(int id) async {
    setState(() => _mine.contains(id) ? _mine.remove(id) : _mine.add(id));
    await _ask('si_prefs', {'my_services': _mine.toList()..sort()});
  }

  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final vpn = AppScope.of(context).vpn;
    final st = _st ?? const {};
    final configured = jBool(st['configured']);
    Widget section(String t, List<Widget> kids) => Padding(
      padding: const EdgeInsets.only(bottom: NbSpace.x4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(t, style: NbType.label(NbSize.body, c.text)),
        const SizedBox(height: 4),
        ...kids,
      ]),
    );
    final note = NbType.text(NbSize.small, c.muted, height: 1.45);
    return NbDialog(
      width: 640,
      title: 'Streaming data sources',
      body: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
        Text('NOBAD uses TMDB for titles and JustWatch data (through TMDB) for availability. Restrictions come from '
            "Wikipedia's banned-film lists.", style: note),
        const SizedBox(height: NbSpace.x3),
        section('TMDB key', [
          Text(
            '${configured ? 'Saved: ${jStr(st['key_hint'])}${st['key_source'] == 'environment' ? ' (from environment)' : ''}' : 'Not set'}. '
            'It is stored encrypted on this PC and only sent to TMDB.',
            style: note,
          ),
          if (!configured) ...[
            const SizedBox(height: 6),
            Text('How to get a free key', style: NbType.label(NbSize.small, c.text)),
            for (final (i, s) in [
              'Create a free TMDB account: $_tmdbSignup (skip if you have one), then confirm your e-mail.',
              'Open the API page: $_tmdbApi (Settings → API).',
              "Request an API key for personal, non-commercial use and accept TMDB's terms. For the app details you can enter: "
                  "name 'NOBAD VPN (personal)', URL https://github.com/nobad-studio/Nobad-VPN, summary 'Personal use of Where to watch in NOBAD VPN'.",
              'Back on $_tmdbApi, copy the API Read Access Token (the long one starting with eyJ, recommended) or the shorter API Key.',
              "Paste it here and press Save & check. NOBAD verifies it with TMDB and stores it encrypted on this PC. Don't share it or put it in NOBAD's source code.",
            ].indexed)
              Text('${i + 1}. $s', style: note),
          ],
          const SizedBox(height: 6),
          Row(children: [
            Expanded(child: NbTextBox(controller: _key, label: '', hint: 'Paste API key or Read Access Token', maxLength: 512)),
            const SizedBox(width: 8),
            NbButton('Save & check', onPressed: _saving ? null : _save),
          ]),
          const SizedBox(height: 6),
          Wrap(spacing: 6, children: [
            NbButton('Open TMDB API page', small: true, kind: NbButtonKind.ghost, onPressed: () => widget.openLink(_tmdbApi)),
            if (configured && st['key_source'] != 'environment')
              NbButton('Remove key', small: true, kind: NbButtonKind.danger, onPressed: () async {
                final nav = Navigator.of(context);
                final ok = await confirmDialog(context, title: 'Remove key', question: 'Remove the saved TMDB key?', yes: 'Remove', danger: true);
                if (!ok) return;
                await _ask('si_key_clear');
                await widget.onChanged();
                nav.pop();
              }),
          ]),
          if (_msg.isNotEmpty) Semantics(liveRegion: true, child: Text(_msg, style: note)),
        ]),
        section('Services you have', [
          Text('Optional. Recommendations prefer countries where a service you have carries the title.', style: note),
          const SizedBox(height: 6),
          Row(children: [
            SizedBox(width: 200, child: NbTextBox(controller: _region, label: '', hint: 'Country code, e.g. IN', maxLength: 2)),
            const SizedBox(width: 8),
            NbButton('Load services', small: true, kind: NbButtonKind.ghost, onPressed: _load),
          ]),
          const SizedBox(height: 6),
          if (_provErr != null)
            Text(_provErr!, style: note)
          else if (_providers == null && configured)
            const _Busy('Loading…')
          else if (_providers != null && _providers!.isEmpty)
            Text('No services found for that country.', style: note)
          else if (_providers != null)
            Wrap(spacing: 6, runSpacing: 6, children: [
              for (final p in _providers!)
                NbChipButton(jStr(p['name']), on: _mine.contains(p['id']), onTap: () => _toggle(jInt(p['id']))),
            ]),
        ]),
        section('Cache', [
          Text('${jInt(jMap(st['cache'])['entries'])} entries. Availability is refreshed after 12 hours; nothing from TMDB is kept longer than 6 months.',
              style: note),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: NbButton('Clear cache', small: true, kind: NbButtonKind.ghost, onPressed: () async {
              final a = await _ask('si_cache_clear');
              if (a != null) vpn.toast('Cache cleared', good: true);
              await _refresh();
            }),
          ),
        ]),
        Text(jStr(st['notice'], tmdbNotice), style: NbType.text(NbSize.caption, c.dim)),
        Text(jStr(st['watch_attribution'], watchAttribution), style: NbType.text(NbSize.caption, c.dim)),
      ]),
      actions: [NbButton('Done', onPressed: () => Navigator.pop(context))],
    );
  }
}

class _TitleTile extends StatelessWidget {
  const _TitleTile({required this.title, required this.sub, this.original, required this.onTap});
  final String title;
  final String sub;
  final String? original;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return SizedBox(
      width: 172,
      child: NbButtonLike(
        onTap: onTap,
        label: title,
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _Poster(letter: title, small: true),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, maxLines: 2, overflow: TextOverflow.ellipsis, style: NbType.label(NbSize.small, c.text)),
              Text(sub, style: NbType.text(NbSize.caption, c.muted)),
              if (original != null) Text(original!, maxLines: 1, overflow: TextOverflow.ellipsis, style: NbType.text(NbSize.caption, c.dim)),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _PlatformTile extends StatelessWidget {
  const _PlatformTile({required this.name, required this.sub, required this.onTap});
  final String name;
  final String sub;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return SizedBox(
      width: 230,
      child: NbButtonLike(
        onTap: onTap,
        label: name,
        child: Row(children: [
          _Poster(letter: name, small: true, square: true),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(name, style: NbType.label(NbSize.small, c.text)),
              Text(sub, maxLines: 2, overflow: TextOverflow.ellipsis, style: NbType.text(NbSize.caption, c.muted)),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// A card-like pressable with hover and focus (the tiles).
class NbButtonLike extends StatelessWidget {
  const NbButtonLike({super.key, required this.onTap, required this.label, required this.child});
  final VoidCallback onTap;
  final String label;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Semantics(
      button: true,
      label: label,
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          onTap: onTap,
          borderRadius: NbRadius.rowAll,
          hoverColor: c.cardHover,
          child: Ink(
            padding: const EdgeInsets.all(NbSpace.x2),
            decoration: BoxDecoration(color: c.card, borderRadius: NbRadius.rowAll, border: Border.all(color: c.line)),
            child: child,
          ),
        ),
      ),
    );
  }
}

/// The neutral stand-in for a poster or logo (the pipe has no image route).
class _Poster extends StatelessWidget {
  const _Poster({required this.letter, this.small = false, this.square = false});
  final String letter;
  final bool small;
  final bool square;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final w = small ? 36.0 : 72.0;
    return ExcludeSemantics(
      child: Container(
        width: w,
        height: square ? w : w * 1.5,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: c.raised, borderRadius: NbRadius.controlAll, border: Border.all(color: c.line)),
        child: Text(letter.isEmpty ? '?' : letter.characters.first.toUpperCase(),
            style: NbType.label(small ? NbSize.title : NbSize.field, c.muted)),
      ),
    );
  }
}

class _Busy extends StatelessWidget {
  const _Busy(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: NbSpace.x2),
      child: Semantics(
        liveRegion: true,
        child: Row(children: [
          SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.6, color: c.orange)),
          const SizedBox(width: 8),
          Flexible(child: Text(text, style: NbType.text(NbSize.small, c.muted))),
        ]),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 12),
      decoration: BoxDecoration(borderRadius: NbRadius.rowAll, border: Border.all(color: c.line2)),
      child: Text(text, textAlign: TextAlign.center, style: NbType.text(NbSize.body, c.muted, height: 1.45)),
    );
  }
}

class _Sub extends StatelessWidget {
  const _Sub(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: NbSpace.x3, bottom: 4),
    child: Text(text, style: NbType.label(NbSize.body, NbColors.of(context).text)),
  );
}

class _Tag extends StatelessWidget {
  const _Tag(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
      decoration: BoxDecoration(borderRadius: NbRadius.pillAll, border: Border.all(color: c.line2)),
      child: Text(text, style: NbType.text(NbSize.caption, c.muted)),
    );
  }
}

/// A country code chip.
class _Cc extends StatelessWidget {
  const _Cc(this.code, {this.tone});
  final String code;
  final Color? tone;
  @override
  Widget build(BuildContext context) {
    final c = NbColors.of(context);
    final col = tone ?? c.text;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(borderRadius: NbRadius.keyAll, border: Border.all(color: col.withValues(alpha: .45))),
      child: Text(code, style: NbType.data(NbSize.caption, col)),
    );
  }
}
