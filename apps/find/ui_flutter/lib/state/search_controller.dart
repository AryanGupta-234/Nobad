/// The words typed, the filters, the answer, the selected row; and what can be done with a row (open, show in
/// folder, copy its path, forget it), always by result id.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../engine/engine_api.dart';
import '../engine/events.dart';
import '../engine/models/result.dart';

import 'recent_searches.dart';
import 'toast_controller.dart';

Future<void> _clipboard(String text) => Clipboard.setData(ClipboardData(text: text));

class FindController extends ChangeNotifier {
  FindController(
    this.engine, {
    this.limit,
    this.debounce = const Duration(milliseconds: 60),
    this.toasts,
    Future<void> Function(String)? copy,
    this.recent,
  }) : _copy = copy ?? _clipboard {
    _sub = engine.events.listen((e) {
      if (e is HereEvent && e.path != _here) {
        _here = e.path;
        if (!_disposed) notifyListeners();
      }
    });
  }

  late final StreamSubscription<EngineEvent> _sub;

  final EngineApi engine;

  /// Recent searches (UI-local); a search is remembered when one of its results is used.
  final RecentSearches? recent;

  void _remember() {
    if (_askedFor.trim().isEmpty) return;
    remember(_askedFor);
  }

  /// A question was used (a result opened, Enter, a suggestion picked): the UI's recent list, and the engine's
  /// search history for autocomplete (kept only while the search_history setting is on; the engine checks).
  void remember(String words) {
    if (words.trim().isEmpty) return;
    final r = recent;
    if (r != null) {
      r.add(words);
      unawaited(r.save());
    }
    unawaited(engine.historyAdd(words).then((_) {}, onError: (Object _) {}));
  }

  /// Time since the last keystroke (the screen records keystroke → paint after the frame).
  Duration get sinceKeystroke => _sinceKeystroke.elapsed;

  /// At most this many rows (the quick find bar shows 8); null = all the engine sends.
  final int? limit;
  final Duration debounce;
  final ToastController? toasts;
  final Future<void> Function(String) _copy;

  String _text = '';
  SearchFilters _filters = SearchFilters.none;
  SearchAnswer _answer = SearchAnswer.empty;
  int _selected = 0;
  String _notice = '';
  bool _busy = false;
  int _seq = 0;
  Timer? _timer;
  bool _disposed = false;
  String _here = '';

  String get text => _text;
  SearchFilters get filters => _filters;
  SearchAnswer get answer => _answer;
  List<FileResult> get results => _answer.results;
  int get selected => _selected;
  FileResult? get current => results.isEmpty ? null : results[_selected.clamp(0, results.length - 1)];
  bool get busy => _busy;

  /// Words, or a filter that narrows: results are shown instead of Home (0.7.0's rule).
  bool get showingResults => _text.trim().isNotEmpty || _filters.narrows;

  /// The File Explorer folder the hotkey was pressed in ('' if none).
  String get here => _here;

  /// A short line under the box: an engine error or "the engine isn't running".
  String get notice => _notice;

  /// Bumped for every new answer (the result list animates each new answer in).
  int serial = 0;

  /// The words as they were when the shown answer was asked for.
  String _askedFor = '';
  String get askedFor => _askedFor;

  /// Milliseconds from asking the engine to having the answer (pipe + search), for the shown answer.
  int _lastMs = 0;
  int get lastMs => _lastMs;

  /// Bumped only when results appear where there were none: the cascade plays then, not on every keystroke
  /// (results that are on screen change in place, so typing never flashes).
  int revealSerial = 0;

  final _sinceKeystroke = Stopwatch();

  /// Milliseconds from the last keystroke to the answer being ready to paint (the screen adds the frame).
  int? lastKeystrokeMs;

  void setText(String t) {
    if (t == _text) return;
    _text = t;
    _sinceKeystroke
      ..reset()
      ..start();
    _schedule();
  }

  void setFilters(SearchFilters f) {
    if (f == _filters) return;
    _filters = f;
    _schedule(now: true);
  }

  void clearFilters() => setFilters(SearchFilters.none);

  Future<void> loadHere() async {
    try {
      _here = await engine.hereFolder();
    } on Object {
      _here = '';
    }
    if (!_disposed) notifyListeners();
  }

  /// Only inside the "here" folder.
  void useHere() {
    if (_here.isNotEmpty) setFilters(_filters.copyWith(folder: _here));
  }

  void _schedule({bool now = false}) {
    _timer?.cancel();
    if (!showingResults) {
      _seq++;
      _answer = SearchAnswer.empty;
      _askedFor = '';
      _selected = 0;
      _notice = '';
      _busy = false;
      notifyListeners();
      return;
    }
    if (now) {
      notifyListeners();
      unawaited(run());
    } else {
      _timer = Timer(debounce, run);
    }
  }

  Future<void> run() async {
    final my = ++_seq;
    final words = _text;
    final filters = _filters;
    if (!showingResults) return;
    _busy = true;
    notifyListeners();
    final clock = Stopwatch()..start();
    SearchAnswer a;
    String notice = '';
    try {
      a = await engine.search(words, filters: filters);
    } on EngineOffline {
      a = SearchAnswer.empty;
      notice = "NOBAD Find's engine isn't running. Start it and the search comes back.";
    } on RpcException catch (e) {
      a = SearchAnswer.empty;
      notice = e.message;
    }
    if (_disposed || my != _seq) return; // a newer search is on its way
    if (a.cancelled) {
      // the engine dropped it for a newer one on this channel: keep what is on screen, say nothing
      _busy = false;
      notifyListeners();
      return;
    }
    final hadNone = _answer.results.isEmpty;
    final lim = limit;
    var rows = a.results;
    if (words.trim().isEmpty) rows = rows.where((r) => !r.weak).toList();
    _answer = lim != null && rows.length > lim
        ? a.copyWith(results: rows.sublist(0, lim), more: true)
        : (identical(rows, a.results) ? a : a.copyWith(results: rows));
    _askedFor = words;
    serial++;
    if (hadNone && rows.isNotEmpty) revealSerial++;
    if (_sinceKeystroke.isRunning) lastKeystrokeMs = _sinceKeystroke.elapsedMilliseconds;
    _lastMs = clock.elapsedMilliseconds;
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
  Future<bool> openSelected() => _act((id) => engine.open(id), "That file isn't there any more.");

  /// Show the selected file in File Explorer.
  Future<bool> revealSelected() => _act((id) => engine.reveal(id), "Couldn't show it in its folder.");

  /// Windows' "Open with" for the selected file (Ctrl+Shift+Enter).
  Future<bool> openWithSelected() => _act((id) => engine.openWith(id), "Couldn't show Open with.");

  /// The selected file's name on the clipboard.
  Future<bool> copyNameSelected() async {
    final r = current;
    if (r == null) return false;
    await _copy(r.name);
    _say('Name copied.');
    return true;
  }

  Future<bool> _act(Future<ActionResult> Function(int id) how, String failed) async {
    _remember();
    final r = current;
    if (r == null) return false;
    var res = const ActionResult(false);
    try {
      res = await how(r.id);
    } on EngineOffline {
      res = const ActionResult(false, "NOBAD Find's engine isn't running.");
    } on RpcException catch (e) {
      res = ActionResult(false, e.message);
    }
    if (!res.ok) _say(res.error.isNotEmpty ? res.error : failed);
    return res.ok;
  }

  /// Ctrl+C: the selected file's full path on the clipboard.
  Future<bool> copySelected() async {
    final r = current;
    if (r == null) return false;
    var path = r.path;
    if (path.isEmpty) {
      try {
        path = await engine.pathOf(r.id);
      } on Object {
        path = '';
      }
    }
    if (path.isEmpty) {
      _say("That file isn't there any more.");
      return false;
    }
    await _copy(path);
    _remember();
    _say('Path copied.');
    return true;
  }

  /// Shift+Delete: after [confirm] says yes, remove the selected file from the index and keep it out.
  Future<bool> forgetSelected(Future<bool> Function(String question) confirm) async {
    final r = current;
    if (r == null) return false;
    if (!await confirm('Forget "${r.name}" and keep it out of the index from now on?')) return false;
    var ok = false;
    try {
      ok = (await engine.forget(r.id)).ok;
    } on Object {
      ok = false;
    }
    if (!ok) return false;
    _say('Forgotten. Undo it in Settings → Never search.');
    if (!_disposed) await run();
    return true;
  }

  void _say(String s) {
    if (toasts != null) {
      toasts!.show(s);
    } else {
      _notice = s;
      if (!_disposed) notifyListeners();
    }
  }

  void clear() => setText('');

  /// Esc: clears the words, else the filters; false when there was nothing left to clear (then the window hides).
  bool clearOne() {
    if (_text.isNotEmpty) {
      setText('');
      return true;
    }
    if (!_filters.isEmpty) {
      clearFilters();
      return true;
    }
    return false;
  }

  String? _handOver;

  /// Words for the search box from outside it (the bar's Alt+Enter), kept until the search screen takes them,
  /// even when another page is open.
  void handOver(String text) {
    _handOver = text;
    if (!_disposed) notifyListeners();
  }

  String? takeHandOver() {
    final t = _handOver;
    _handOver = null;
    return t;
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    _sub.cancel();
    super.dispose();
  }
}
