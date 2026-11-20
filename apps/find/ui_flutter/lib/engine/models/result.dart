/// One search result and one search answer, as the engine sends them (`search` in nobadfind/search.py).
///
/// Everything here comes from the index: file names, folders and snippets are untrusted text. They are only ever
/// shown as plain text (Text / TextSpan), never parsed as markup.
library;

export 'format.dart' show humanSize;

String _str(Object? v) => v is String ? v : '';
int? _int(Object? v) => v is int ? v : (v is double && v.isFinite ? v.toInt() : null);
List<String> _strs(Object? v) => v is List
    ? [
        for (final x in v)
          if (x is String) x,
      ]
    : const [];

class FileResult {
  const FileResult({
    required this.id,
    required this.name,
    this.path = '',
    this.dir = '',
    this.kind = 'other',
    this.size,
    this.mtime,
    this.ago = '',
    this.snippet = '',
    this.why = const [],
    this.weak = false,
  });

  final int id;
  final String name;

  /// The full path (contract `Result.path`), for Copy path; '' from an engine that doesn't send it.
  final String path;
  final String dir;
  final String kind;
  final int? size;
  final double? mtime;
  final String ago;

  /// Words around the match; \x02 … \x03 mark the matched words.
  final String snippet;
  final List<String> why;
  final bool weak;

  static const thumbKinds = {'image', 'video', 'pdf'};
  bool get hasThumb => thumbKinds.contains(kind);

  /// Null when the row has no usable id (it can't be opened, so it isn't shown).
  static FileResult? fromJson(Object? json) {
    if (json is! Map) return null;
    final id = json['id'];
    if (id is! int) return null;
    final mt = json['mtime'];
    return FileResult(
      id: id,
      name: _str(json['name']),
      path: _str(json['path']),
      dir: _str(json['dir']).isNotEmpty ? _str(json['dir']) : _str(json['folder']),
      kind: _str(json['kind']).isEmpty ? 'other' : _str(json['kind']),
      size: _int(json['size']),
      mtime: mt is num && mt.isFinite ? mt.toDouble() : null,
      ago: _str(json['ago']),
      snippet: _str(json['snippet']),
      why: _strs(json['why']),
      weak: json['weak'] == true,
    );
  }
}

/// One part of how the question was understood (contract `Part`, 0.8.5): a removable chip.
class QueryPart {
  const QueryPart({required this.kind, required this.label, this.without = ''});

  /// folder | drive | kind | time | size | sort | meaning | words.
  final String kind;

  /// The chip's text, plain (it may be the user's own words or a folder name from the index).
  final String label;

  /// The question with this part taken out: removing the chip searches this.
  final String without;

  bool get isMeaning => kind == 'meaning' || kind == 'words';

  static QueryPart? fromJson(Object? json) {
    if (json is! Map) return null;
    final label = _str(json['label']);
    if (label.isEmpty) return null;
    return QueryPart(kind: _str(json['kind']), label: label, without: _str(json['without']));
  }
}

/// The best guess (contract `BestGuess`): the one result the engine is sure of; always `results[0]`.
class BestGuess {
  const BestGuess(this.id, this.reason);
  final int id;
  final String reason;

  static BestGuess? fromJson(Object? json) {
    if (json is! Map || json['id'] is! int) return null;
    return BestGuess(json['id'] as int, _str(json['reason']));
  }
}

/// One autocomplete suggestion (contract `Suggestion`, `suggest`).
class Suggestion {
  const Suggestion({required this.text, required this.kind, required this.label, this.detail = '', this.id});

  /// The whole question to search when it's picked.
  final String text;

  /// history | filter | file | folder.
  final String kind;
  final String label;
  final String detail;
  final int? id;

  bool get isHistory => kind == 'history';

  static Suggestion? fromJson(Object? json) {
    if (json is! Map) return null;
    final text = _str(json['text']);
    final kind = _str(json['kind']);
    if (text.isEmpty || !const {'history', 'filter', 'file', 'folder'}.contains(kind)) return null;
    final id = json['id'];
    return Suggestion(
      text: text,
      kind: kind,
      label: _str(json['label']).isEmpty ? text : _str(json['label']),
      detail: _str(json['detail']),
      id: id is int ? id : null,
    );
  }
}

/// `suggest`'s answer: the list and the inline (ghost) completion of what's typed.
class Suggestions {
  const Suggestions({this.items = const [], this.complete = ''});
  final List<Suggestion> items;

  /// Starts with exactly the typed text, or ''.
  final String complete;

  static const none = Suggestions();

  static Suggestions fromJson(Object? json) {
    if (json is! Map) return none;
    final rows = json['items'];
    return Suggestions(
      items: rows is List ? [for (final r in rows) ?Suggestion.fromJson(r)] : const [],
      complete: _str(json['complete']),
    );
  }
}

class SearchAnswer {
  const SearchAnswer({
    this.results = const [],
    this.ms = 0,
    this.understood = const [],
    this.terms = const [],
    this.notes = const [],
    this.more = false,
    this.error = '',
    this.cancelled = false,
    this.parts = const [],
    this.best,
  });

  /// How the question was understood, as removable chips (0.8.5; an older engine: empty, see [understood]).
  final List<QueryPart> parts;

  /// The best guess, or null when the engine isn't sure. When set it is `results[0]`.
  final BestGuess? best;

  /// [best] when it really is the first row shown.
  bool get hasGuess => best != null && results.isNotEmpty && results.first.id == best!.id;

  SearchAnswer copyWith({List<FileResult>? results, bool? more}) => SearchAnswer(
    results: results ?? this.results,
    ms: ms,
    understood: understood,
    terms: terms,
    notes: notes,
    more: more ?? this.more,
    error: error,
    cancelled: cancelled,
    parts: parts,
    best: best,
  );

  /// A newer search on the same channel replaced this one: ignore the answer (no message, no empty state).
  final bool cancelled;

  final List<FileResult> results;
  final int ms;
  final List<String> understood;

  /// The words to highlight in names and snippets (contract `terms`).
  final List<String> terms;
  final List<String> notes;
  final bool more;
  final String error;

  static const empty = SearchAnswer();

  static SearchAnswer fromJson(Object? json) {
    if (json is! Map) return const SearchAnswer(error: 'The engine sent something unexpected.');
    final rows = json['results'];
    return SearchAnswer(
      results: rows is List ? [for (final r in rows) ?FileResult.fromJson(r)] : const [],
      ms: _int(json['ms']) ?? 0,
      understood: _strs(json['understood']),
      terms: _strs(json['terms']),
      notes: _strs(json['notes']),
      more: json['more'] == true,
      error: _str(json['error']),
      cancelled: json['cancelled'] == true,
      parts: json['parts'] is List ? [for (final p in json['parts'] as List) ?QueryPart.fromJson(p)] : const [],
      best: BestGuess.fromJson(json['best']),
    );
  }
}

const kindTags = {
  'pdf': 'PDF',
  'document': 'DOC',
  'spreadsheet': 'XLS',
  'slides': 'PPT',
  'text': 'TXT',
  'code': '</>',
  'email': 'MAIL',
  'image': 'IMG',
  'video': 'VID',
  'audio': 'AUD',
  'archive': 'ZIP',
  'app': 'APP',
  'ebook': 'BOOK',
  'folder': 'DIR',
  'other': 'FILE',
};

String kindTag(String kind) => kindTags[kind] ?? 'FILE';

/// The filter bar (kind, date, size, folder, order), combined by the engine with whatever the words say.
/// Values are the 0.7.0 page's option values; '' means "any".
class SearchFilters {
  const SearchFilters({this.kind = '', this.modified = '', this.size = '', this.folder = '', this.sort = ''});
  final String kind;
  final String modified;
  final String size;
  final String folder;
  final String sort;

  static const none = SearchFilters();

  /// A filter that narrows the results (the order alone doesn't).
  bool get narrows => kind.isNotEmpty || modified.isNotEmpty || size.isNotEmpty || folder.isNotEmpty;
  bool get isEmpty => !narrows && sort.isEmpty;

  SearchFilters copyWith({String? kind, String? modified, String? size, String? folder, String? sort}) => SearchFilters(
    kind: kind ?? this.kind,
    modified: modified ?? this.modified,
    size: size ?? this.size,
    folder: folder ?? this.folder,
    sort: sort ?? this.sort,
  );

  /// The `filters` object of the `search` call (the same keys as 0.7.0's page sent).
  Map<String, Object?> toJson() => {
    'kind': kind, 'modified': modified, 'size': size,
    'folder': folder.length > 2000 ? '' : folder, // the engine refuses longer (contract: at most 2000)
    'sort': sort,
  };

  @override
  bool operator ==(Object other) =>
      other is SearchFilters &&
      other.kind == kind &&
      other.modified == modified &&
      other.size == size &&
      other.folder == folder &&
      other.sort == sort;

  @override
  int get hashCode => Object.hash(kind, modified, size, folder, sort);
}

/// The filter bar's choices, with the 0.7.0 labels.
abstract final class FilterChoices {
  static const kind = [
    ('', 'Any kind'),
    ('pdf', 'PDFs'),
    ('document', 'Documents'),
    ('spreadsheet', 'Spreadsheets'),
    ('slides', 'Slides'),
    ('text', 'Text and notes'),
    ('code', 'Code'),
    ('email', 'E-mail'),
    ('image', 'Images'),
    ('video', 'Videos'),
    ('audio', 'Audio'),
    ('archive', 'Archives'),
    ('ebook', 'E-books'),
    ('app', 'Programs'),
    ('folder', 'Folders'),
  ];
  static const modified = [
    ('', 'Any time'),
    ('today', 'Today'),
    ('week', 'Last 7 days'),
    ('month', 'Last 30 days'),
    ('year', 'Last 12 months'),
  ];
  static const size = [('', 'Any size'), ('small', 'Under 1 MB'), ('medium', '1 to 100 MB'), ('large', 'Over 100 MB')];
  static const sort = [
    ('', 'Best match'),
    ('newest', 'Newest first'),
    ('oldest', 'Oldest first'),
    ('largest', 'Largest first'),
    ('name', 'By name'),
  ];
}

final _trailingSlashes = RegExp(r'[\\/]+$');
final _slash = RegExp(r'[\\/]');

/// The folder's own name, for the filter button ("Taxes" for a path ending in \Taxes\).
String baseName(String p) {
  final parts = p.replaceAll(_trailingSlashes, '').split(_slash);
  return parts.isEmpty || parts.last.isEmpty ? p : parts.last;
}
