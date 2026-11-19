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
  });

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
