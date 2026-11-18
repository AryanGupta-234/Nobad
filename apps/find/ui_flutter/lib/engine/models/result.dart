/// One search result and one search answer, as the engine sends them (`search` in nobadfind/search.py).
///
/// Everything here comes from the index: file names, folders and snippets are untrusted text. They are only ever
/// shown as plain text (Text / TextSpan), never parsed as markup.
library;

String _str(Object? v) => v is String ? v : '';
int? _int(Object? v) => v is int ? v : (v is double && v.isFinite ? v.toInt() : null);
List<String> _strs(Object? v) => v is List ? [for (final x in v) if (x is String) x] : const [];

class FileResult {
  const FileResult({
    required this.id,
    required this.name,
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
    this.notes = const [],
    this.more = false,
    this.error = '',
  });

  final List<FileResult> results;
  final int ms;
  final List<String> understood;
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
      notes: _strs(json['notes']),
      more: json['more'] == true,
      error: _str(json['error']),
    );
  }
}

/// "12 KB", "3.4 MB" (the same steps as the 0.7.0 page).
String humanSize(int? n) {
  if (n == null || n <= 0) return '';
  if (n < 1024) return '$n B';
  if (n < 1 << 20) return '${(n / 1024).toStringAsFixed(0)} KB';
  if (n < 1 << 30) return '${(n / 1048576).toStringAsFixed(1)} MB';
  return '${(n / 1073741824).toStringAsFixed(2)} GB';
}

const kindTags = {
  'pdf': 'PDF', 'document': 'DOC', 'spreadsheet': 'XLS', 'slides': 'PPT', 'text': 'TXT', 'code': '</>',
  'email': 'MAIL', 'image': 'IMG', 'video': 'VID', 'audio': 'AUD', 'archive': 'ZIP', 'app': 'APP',
  'ebook': 'BOOK', 'folder': 'DIR', 'other': 'FILE',
};

String kindTag(String kind) => kindTags[kind] ?? 'FILE';
