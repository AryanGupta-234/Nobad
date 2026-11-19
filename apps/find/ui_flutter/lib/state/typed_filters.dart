/// Words that mean a filter ("pdf", "last week", "in downloads"): offered as a filter chip while typing (Tab
/// accepts it: the words leave the box and the filter is set), and used to take an "understood" chip back out.
library;

import '../engine/models/result.dart';

class TypedRule {
  const TypedRule(this.pattern, this.label, this.filters);
  final RegExp pattern;
  final String label;
  final SearchFilters filters;
}

RegExp _w(String alternatives, {String lead = ''}) =>
    RegExp('(?:^|\\s)(?:$lead)($alternatives)(?=\\s|\$)', caseSensitive: false);

const _timeLead = r'(?:from |in |since |of )?';

final _rules = <TypedRule>[
  TypedRule(_w('pdfs?'), 'Kind: PDFs', const SearchFilters(kind: 'pdf')),
  TypedRule(_w('photos?|images?|pictures?|pics'), 'Kind: Images', const SearchFilters(kind: 'image')),
  TypedRule(_w('docs?|documents?'), 'Kind: Documents', const SearchFilters(kind: 'document')),
  TypedRule(_w('spreadsheets?|excel|sheets'), 'Kind: Spreadsheets', const SearchFilters(kind: 'spreadsheet')),
  TypedRule(_w('slides|presentations?|decks?'), 'Kind: Slides', const SearchFilters(kind: 'slides')),
  TypedRule(_w('videos?|movies?|clips?'), 'Kind: Videos', const SearchFilters(kind: 'video')),
  TypedRule(_w('music|songs?|audio'), 'Kind: Audio', const SearchFilters(kind: 'audio')),
  TypedRule(_w('zips?|archives?'), 'Kind: Archives', const SearchFilters(kind: 'archive')),
  TypedRule(_w('emails?|mails?'), 'Kind: E-mail', const SearchFilters(kind: 'email')),
  TypedRule(_w('today', lead: _timeLead), 'Changed: Today', const SearchFilters(modified: 'today')),
  TypedRule(
    _w('(?:last|this|past) week', lead: _timeLead),
    'Changed: Last 7 days',
    const SearchFilters(modified: 'week'),
  ),
  TypedRule(
    _w('(?:last|this|past) month', lead: _timeLead),
    'Changed: Last 30 days',
    const SearchFilters(modified: 'month'),
  ),
  TypedRule(
    _w('(?:last|this|past) year', lead: _timeLead),
    'Changed: Last 12 months',
    const SearchFilters(modified: 'year'),
  ),
  for (final f in ['downloads', 'documents', 'desktop', 'pictures', 'videos', 'music'])
    TypedRule(
      _w(f, lead: r'(?:in |from )(?:my |the )?'),
      'Folder: ${f[0].toUpperCase()}${f.substring(1)}',
      SearchFilters(folder: f),
    ),
];

/// A filter the words mean, and how to take those words out.
class TypedFilter {
  const TypedFilter(this.label, this.filters, this._rule);
  final String label;
  final SearchFilters filters;
  final TypedRule _rule;

  /// The words without this filter's words, and [current] with the filter set.
  (String, SearchFilters) accept(String text, SearchFilters current) {
    final out = _strip(text, _rule.pattern);
    final f = filters;
    return (
      out,
      current.copyWith(
        kind: f.kind.isEmpty ? null : f.kind,
        modified: f.modified.isEmpty ? null : f.modified,
        folder: f.folder.isEmpty ? null : f.folder,
      ),
    );
  }
}

String _strip(String text, RegExp p) => text.replaceFirst(p, ' ').replaceAll(RegExp(r'\s+'), ' ').trim();

/// Filters the words mean, in the order they appear (one per kind of filter).
List<TypedFilter> suggestFilters(String text) {
  final found = <(int, TypedFilter)>[];
  final seen = <String>{};
  for (final r in _rules) {
    final m = r.pattern.firstMatch(text);
    if (m == null) continue;
    final kind = r.filters.kind.isNotEmpty
        ? 'kind'
        : r.filters.modified.isNotEmpty
        ? 'modified'
        : 'folder';
    if (!seen.add(kind)) continue;
    found.add((m.start, TypedFilter(r.label, r.filters, r)));
  }
  found.sort((a, b) => a.$1.compareTo(b.$1));
  // the box must keep some words: a lone "pdf" stays a search for "pdf"
  return [
    for (final (_, f) in found)
      if (_strip(text, f._rule.pattern).isNotEmpty) f,
  ];
}

/// The words without the ones an "understood" chip came from, or null if this UI can't tell which they were.
String? removeUnderstood(String text, String chip) {
  final c = chip.toLowerCase();
  bool has(Iterable<String> keys) => keys.any(c.contains);
  TypedRule? rule;
  for (final r in _rules) {
    final f = r.filters;
    final hit = switch ((f.kind, f.modified, f.folder)) {
      ('pdf', _, _) => has(['pdf']),
      ('image', _, _) => has(['photo', 'image', 'picture']),
      ('document', _, _) => has(['document']),
      ('spreadsheet', _, _) => has(['spreadsheet']),
      ('slides', _, _) => has(['slide', 'presentation']),
      ('video', _, _) => has(['video']),
      ('audio', _, _) => has(['audio', 'music']),
      ('archive', _, _) => has(['archive', 'zip']),
      ('email', _, _) => has(['mail']),
      (_, 'today', _) => has(['today']),
      (_, 'week', _) => has(['7 days', 'week']),
      (_, 'month', _) => has(['30 days', 'month']),
      (_, 'year', _) => has(['12 months', 'year']),
      (_, _, final folder) => folder.isNotEmpty && has([folder]),
    };
    if (hit && r.pattern.hasMatch(text)) {
      rule = r;
      break;
    }
  }
  return rule == null ? null : _strip(text, rule.pattern);
}
