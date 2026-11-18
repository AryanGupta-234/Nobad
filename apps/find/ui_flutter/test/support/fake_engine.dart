import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:nobad_find/engine/events.dart';
import 'package:nobad_find/engine/models/result.dart';
import 'package:nobad_find/engine/models/status.dart';
import 'package:nobad_find/engine/rpc.dart';
import 'package:nobad_find/platform/window.dart';

/// An engine without a pipe: answers from a list, records what the UI asked for.
class FakeEngine implements Engine {
  FakeEngine({List<FileResult>? files, Link link = Link.connected}) : files = files ?? sampleFiles() {
    _link.value = link;
  }

  final List<FileResult> files;
  final _link = ValueNotifier(Link.connected);
  final _events = StreamController<EngineEvent>.broadcast(sync: true);
  final searches = <String>[];
  final opened = <int>[];
  final revealed = <int>[];
  final thumbsAsked = <int>[];
  bool openOk = true;
  bool offline = false;
  EngineStatus? status;

  set linkState(Link l) => _link.value = l;
  void emit(EngineEvent e) {
    if (e is StatusEvent) status = e.status;
    _events.add(e);
  }

  @override
  ValueListenable<Link> get link => _link;
  @override
  Stream<EngineEvent> get events => _events.stream;
  @override
  EngineStatus? get lastStatus => status;

  @override
  Future<SearchAnswer> search(String text, {Map<String, Object?> filters = const {}}) async {
    searches.add(text);
    if (offline) throw const EngineOffline();
    final t = text.trim().toLowerCase();
    final rows = files.where((f) => f.name.toLowerCase().contains(t)).toList();
    return SearchAnswer(results: rows, ms: 4, understood: t.contains('pdf') ? const ['pdf files'] : const []);
  }

  @override
  Future<bool> open(int id) async {
    opened.add(id);
    return openOk;
  }

  @override
  Future<bool> reveal(int id) async {
    revealed.add(id);
    return true;
  }

  @override
  Future<Uint8List?> thumbnail(int id) async {
    thumbsAsked.add(id);
    return null;
  }

  @override
  void dispose() {
    _events.close();
  }
}

class FakeWindow implements WindowControl {
  final calls = <String>[];
  final fits = <int>[];
  @override
  void hide() => calls.add('hide');
  @override
  void showBar() => calls.add('showBar');
  @override
  void fitBar(int rows) => fits.add(rows);
  @override
  void front() => calls.add('front');
}

List<FileResult> sampleFiles() => const [
      FileResult(id: 1, name: 'tax return 2025.pdf', dir: r'C:\Users\me\Documents\Taxes', kind: 'pdf',
          size: 482113, ago: '3 days ago', why: ['name matches'], snippet: 'your \x02tax\x03 refund is'),
      FileResult(id: 2, name: 'tax notes.txt', dir: r'C:\Users\me\Desktop', kind: 'text', size: 912, ago: '1 h ago',
          why: ['name matches']),
      FileResult(id: 3, name: 'beach.jpg', dir: r'C:\Users\me\Pictures\2026\March', kind: 'image', size: 3400000,
          ago: 'March', why: ['the picture may show it']),
      FileResult(id: 4, name: '<b>tax</b> & "quotes".docx', dir: r'D:\Work', kind: 'document', size: 20000,
          ago: '2 weeks ago', why: ['text inside matches']),
      FileResult(id: 5, name: 'old tax scan.pdf', dir: r'C:\Users\me\Scans', kind: 'pdf', size: 1200000,
          ago: 'last year', weak: true, why: ['text has a loose meaning']),
    ];

List<FileResult> manyFiles(int n) => [
      for (var i = 0; i < n; i++)
        FileResult(id: 100 + i, name: 'report $i.pdf', dir: r'C:\Users\me\Reports\Quarterly\Archive', kind: 'pdf'),
    ];
