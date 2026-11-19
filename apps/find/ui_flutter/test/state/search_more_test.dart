import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/state/recent_searches.dart';
import 'package:nobad_find/state/search_controller.dart';
import 'package:nobad_find/state/typed_filters.dart';

import '../support/fake_engine.dart';

void main() {
  group('recent searches (kept by the UI, on this PC only)', () {
    late Directory dir;
    setUp(() => dir = Directory.systemTemp.createTempSync('nf-recent'));
    tearDown(() => dir.deleteSync(recursive: true));

    test('newest first, no repeats, at most 8, kept across starts, clearable', () async {
      final f = File('${dir.path}/recent.json');
      final r = RecentSearches(f);
      for (final w in ['a', 'tax', 'b', 'TAX ', 'c', 'd', 'e', 'f', 'g', 'h']) {
        r.add(w);
      }
      expect(r.items.first, 'h');
      expect(r.items.where((w) => w.toLowerCase() == 'tax'), hasLength(1));
      expect(r.items, hasLength(8));
      await r.save();
      final again = RecentSearches(f);
      await again.load();
      expect(again.items, r.items);
      await again.clear();
      expect(again.items, isEmpty);
      expect(f.existsSync(), isFalse);
      r.add('   ');
      expect(r.items.contains(''), isFalse);
    });
  });

  group('typed filters', () {
    test('words that mean a filter are offered as one', () {
      expect(suggestFilters('rent pdf').map((s) => s.label), ['Kind: PDFs']);
      expect(suggestFilters('photos from last week').map((s) => s.label), ['Kind: Images', 'Changed: Last 7 days']);
      expect(suggestFilters('notes in downloads').single.filters.folder, 'downloads');
      expect(suggestFilters('notes'), isEmpty);
    });

    test('accepting one takes its words out and sets the filter', () {
      final s = suggestFilters('rent pdf from last week').first;
      final (text, filters) = s.accept('rent pdf from last week', SearchFilters.none);
      expect(text, 'rent from last week');
      expect(filters.kind, 'pdf');
    });

    test('an understood chip can be removed by taking out the words it came from', () {
      expect(removeUnderstood('rent pdf from last week', 'pdf'), 'rent from last week');
      expect(removeUnderstood('rent pdf from last week', 'changed in the last 7 days'), 'rent pdf');
      expect(removeUnderstood('beach', 'something the engine said'), isNull);
    });
  });

  test('a new answer for the same search does not replay the reveal; the first one does', () async {
    final f = FindController(FakeEngine(), debounce: Duration.zero);
    f.setText('tax');
    await f.run();
    final first = f.revealSerial;
    f.setText('tax n');
    await f.run();
    expect(f.revealSerial, first); // results were on screen: they change in place
    f.setText('');
    f.setText('tax');
    await f.run();
    expect(f.revealSerial, first + 1);
    expect(f.lastKeystrokeMs, isNotNull);
    f.dispose();
  });

  test('a cancelled answer is ignored: what is on screen stays, no message', () async {
    final engine = _Cancelling();
    final f = FindController(engine, debounce: Duration.zero);
    f.setText('tax');
    await f.run();
    final shown = f.results.length;
    expect(shown, greaterThan(0));
    engine.cancelNext = true;
    f.setText('tax n');
    await f.run();
    expect(f.results.length, shown);
    expect(f.notice, isEmpty);
    expect(f.busy, isFalse);
    f.dispose();
  });

  test('searches say their channel; the answer reads cancelled', () {
    expect(SearchAnswer.fromJson({'results': [], 'cancelled': true}).cancelled, isTrue);
    expect(SearchAnswer.fromJson({'results': []}).cancelled, isFalse);
  });
}

class _Cancelling extends FakeEngine {
  bool cancelNext = false;

  @override
  Future<SearchAnswer> search(String text, {SearchFilters filters = SearchFilters.none, String channel = 'main'}) {
    if (cancelNext) {
      cancelNext = false;
      return Future.value(const SearchAnswer(cancelled: true));
    }
    return super.search(text, filters: filters, channel: channel);
  }
}
