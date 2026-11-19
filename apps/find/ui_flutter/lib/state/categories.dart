/// The sidebar's search categories: each is a pre-filtered search (the contract's `kind`, `folder`, `modified`
/// and `sort` words) with its own starting tiles. Which one is lit is read from the filters in use, so changing a
/// filter by hand or with typed words keeps the sidebar honest.
library;

import '../engine/models/result.dart';

/// A starting tile inside a category: a label and the filters it sets.
typedef CategoryTile = (String label, String badge, SearchFilters filters);

enum SearchCategory {
  all('All', SearchFilters.none),
  documents('Documents', SearchFilters(kind: 'document')),
  photos('Photos & images', SearchFilters(kind: 'image')),
  media('Videos & music', SearchFilters(kind: 'video')),
  code('Code & projects', SearchFilters(kind: 'code')),
  downloads('Downloads', SearchFilters(folder: 'downloads', sort: 'newest')),
  recent('Recent', SearchFilters(modified: 'week', sort: 'newest'));

  const SearchCategory(this.label, this.filters);
  final String label;
  final SearchFilters filters;

  static const _docKinds = {'document', 'pdf', 'spreadsheet', 'slides', 'text', 'ebook', 'email'};

  /// The category these filters belong to (a folder beats a kind beats a time).
  static SearchCategory of(SearchFilters f) {
    if (f.folder == 'downloads') return downloads;
    if (_docKinds.contains(f.kind)) return documents;
    if (f.kind == 'image') return photos;
    if (f.kind == 'video' || f.kind == 'audio') return media;
    if (f.kind == 'code') return code;
    if (f.kind.isEmpty && f.modified.isNotEmpty && f.folder.isEmpty) return recent;
    return all;
  }

  /// The tiles shown while the box is empty: narrower searches inside the category.
  List<CategoryTile> get tiles => switch (this) {
    all => const [
      ('Documents', 'DOC', SearchFilters(kind: 'document')),
      ('PDFs', 'PDF', SearchFilters(kind: 'pdf')),
      ('Photos', 'IMG', SearchFilters(kind: 'image')),
      ('Videos', 'VID', SearchFilters(kind: 'video')),
      ('Code', 'SRC', SearchFilters(kind: 'code')),
      ('Downloads', 'DL', SearchFilters(folder: 'downloads', sort: 'newest')),
    ],
    documents => const [
      ('Word & documents', 'DOC', SearchFilters(kind: 'document')),
      ('PDFs', 'PDF', SearchFilters(kind: 'pdf')),
      ('Spreadsheets', 'XLS', SearchFilters(kind: 'spreadsheet')),
      ('Slides', 'PPT', SearchFilters(kind: 'slides')),
      ('Text & notes', 'TXT', SearchFilters(kind: 'text')),
      ('E-mail files', 'EML', SearchFilters(kind: 'email')),
    ],
    photos => const [
      ('All photos', 'IMG', SearchFilters(kind: 'image')),
      ('Today', '1D', SearchFilters(kind: 'image', modified: 'today', sort: 'newest')),
      ('This week', '7D', SearchFilters(kind: 'image', modified: 'week', sort: 'newest')),
      ('This month', '30D', SearchFilters(kind: 'image', modified: 'month', sort: 'newest')),
      ('Large', 'XL', SearchFilters(kind: 'image', size: 'large', sort: 'largest')),
    ],
    media => const [
      ('Videos', 'VID', SearchFilters(kind: 'video')),
      ('Music & audio', 'AUD', SearchFilters(kind: 'audio')),
      ('Large videos', 'XL', SearchFilters(kind: 'video', size: 'large', sort: 'largest')),
      ('New videos', '7D', SearchFilters(kind: 'video', modified: 'week', sort: 'newest')),
    ],
    code => const [
      ('All code', 'SRC', SearchFilters(kind: 'code')),
      ('Changed today', '1D', SearchFilters(kind: 'code', modified: 'today', sort: 'newest')),
      ('This week', '7D', SearchFilters(kind: 'code', modified: 'week', sort: 'newest')),
      ('Archives', 'ZIP', SearchFilters(kind: 'archive')),
    ],
    downloads => const [
      ('Newest', 'NEW', SearchFilters(folder: 'downloads', sort: 'newest')),
      ('PDFs', 'PDF', SearchFilters(folder: 'downloads', kind: 'pdf', sort: 'newest')),
      ('Installers', 'APP', SearchFilters(folder: 'downloads', kind: 'app', sort: 'newest')),
      ('Archives', 'ZIP', SearchFilters(folder: 'downloads', kind: 'archive', sort: 'newest')),
      ('Images', 'IMG', SearchFilters(folder: 'downloads', kind: 'image', sort: 'newest')),
      ('Largest', 'XL', SearchFilters(folder: 'downloads', sort: 'largest')),
    ],
    recent => const [
      ('Today', '1D', SearchFilters(modified: 'today', sort: 'newest')),
      ('This week', '7D', SearchFilters(modified: 'week', sort: 'newest')),
      ('This month', '30D', SearchFilters(modified: 'month', sort: 'newest')),
      ('This year', '1Y', SearchFilters(modified: 'year', sort: 'newest')),
    ],
  };
}
