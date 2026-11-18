/// The words typed, the answer, the selected row; opening and revealing by result id.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/models/result.dart';
import '../engine/rpc.dart';

class FindController extends ChangeNotifier {
  FindController(this.engine, {this.limit, this.debounce = const Duration(milliseconds: 60)});

  final Engine engine;

  /// At most this many rows (the quick find bar shows 8); null = all the engine sends.
  final int? limit;
  final Duration debounce;

  String _text = '';
  SearchAnswer _answer = SearchAnswer.empty;
  int _selected = 0;
  String _notice = '';
  bool _busy = false;
  int _seq = 0;
  Timer? _timer;
  bool _disposed = false;

  String get text => _text;
  SearchAnswer get answer => _answer;
  List<FileResult> get results => _answer.results;
  int get selected => _selected;
  FileResult? get current => results.isEmpty ? null : results[_selected.clamp(0, results.length - 1)];
  bool get busy => _busy;

  /// A short line for the user: an error from the engine, or "the file isn't there any more".
  String get notice => _notice;

  /// The words as they were when the shown answer was asked for.
  String _askedFor = '';
  String get askedFor => _askedFor;

  void setText(String t) {
    if (t == _text) return;
    _text = t;
    _timer?.cancel();
    if (t.trim().isEmpty) {
      _seq++;
      _answer = SearchAnswer.empty;
      _askedFor = '';
      _selected = 0;
      _notice = '';
      _busy = false;
      notifyListeners();
      return;
    }
    _timer = Timer(debounce, run);
  }

  Future<void> run() async {
    final my = ++_seq;
    final words = _text;
    if (words.trim().isEmpty) return;
    _busy = true;
    notifyListeners();
    SearchAnswer a;
    String notice = '';
    try {
      a = await engine.search(words);
    } on EngineOffline {
      a = SearchAnswer.empty;
      notice = "NOBAD Find's engine isn't running. Start it and the search comes back.";
    } on RpcException catch (e) {
      a = SearchAnswer.empty;
      notice = e.message;
    }
    if (_disposed || my != _seq) return; // a newer search is on its way
    final lim = limit;
    _answer = lim != null && a.results.length > lim
        ? SearchAnswer(results: a.results.sublist(0, lim), ms: a.ms, understood: a.understood, notes: a.notes,
            more: true, error: a.error)
        : a;
    _askedFor = words;
    _selected = 0;
    _notice = notice.isNotEmpty ? notice : a.error;
    _busy = false;
    notifyListeners();
  }

  void move(int delta) {
    if (results.isEmpty) return;
    _selected = (_selected + delta) % results.length;
    if (_selected < 0) _selected += results.length;
    notifyListeners();
  }

  void select(int i) {
    if (i < 0 || i >= results.length || i == _selected) return;
    _selected = i;
    notifyListeners();
  }

  /// Open the selected file with its default program (the engine does it, by id). True if it opened.
  Future<bool> openSelected() => _act(engine.open);

  /// Show the selected file in File Explorer.
  Future<bool> revealSelected() => _act(engine.reveal);

  Future<bool> _act(Future<bool> Function(int id) how) async {
    final r = current;
    if (r == null) return false;
    var ok = false;
    try {
      ok = await how(r.id);
    } on EngineOffline {
      _notice = "NOBAD Find's engine isn't running.";
    } on RpcException catch (e) {
      _notice = e.message;
    }
    if (!ok && _notice.isEmpty) _notice = "That file isn't there any more.";
    if (!_disposed) notifyListeners();
    return ok;
  }

  void clear() => setText('');

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}
