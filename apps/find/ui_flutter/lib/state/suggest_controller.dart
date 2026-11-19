/// Autocomplete for a search box (0.8.5): asks the engine's `suggest` as the user types, keeps the list, the
/// highlighted row and the inline ghost completion. Shared by the main window's box and the quick find bar.
///
/// Keys (the screens route them here): ↑ from the first result goes up into the list, ↓ comes back down (see
/// [up] and [down]); Tab or → at the end of the text take the ghost completion; Enter takes the highlighted row
/// (with none highlighted, Enter is the screen's: it opens the best guess); Esc closes the list first.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../engine/engine_api.dart';
import '../engine/models/result.dart';

class SuggestController extends ChangeNotifier {
  /// [debounce]: a pause in typing before asking (70 ms: one ask per burst of keys, never in the way of typing).
  SuggestController(this.engine, {this.channel = 'main', this.debounce = const Duration(milliseconds: 70)});

  final EngineApi engine;
  final String channel;
  final Duration debounce;

  Suggestions _s = Suggestions.none;
  String _for = '';
  int _hi = -1;
  bool _open = false;
  bool _disposed = false;
  int _seq = 0;
  Timer? _timer;

  /// The suggestions for [askedFor] (less the files already on show, see [exclude]).
  List<Suggestion> get items => _exclude.isEmpty
      ? _s.items
      : [
          for (final i in _s.items)
            if (i.id == null || !_exclude.contains(i.id)) i,
        ];

  Set<int> _exclude = const {};

  /// Result ids on show right below the list (the bar): their names aren't offered again.
  set exclude(Set<int> ids) {
    if (setEquals(ids, _exclude)) return;
    final cur = current;
    _exclude = ids;
    _hi = cur == null ? -1 : items.indexOf(cur);
    if (!_disposed) notifyListeners();
  }

  /// The text they were asked for.
  String get askedFor => _for;

  /// The highlighted row, or -1 (none: Enter belongs to the results).
  int get highlighted => _hi;
  Suggestion? get current => _hi >= 0 && _hi < items.length ? items[_hi] : null;

  /// The list is showing (it has rows and the user hasn't closed it since typing).
  bool get isOpen => _open && items.isNotEmpty;

  /// What's typed plus the rest of the best completion, or '' (it always starts with exactly the typed text).
  String ghostFor(String typed) {
    final c = _s.complete;
    if (typed.isEmpty || typed != _for || c.length <= typed.length || !c.startsWith(typed)) return '';
    return c.substring(typed.length);
  }

  /// The words changed by typing: ask again (the list opens when it has rows).
  void typed(String text) {
    _timer?.cancel();
    _hi = -1;
    if (text.trim().isEmpty) {
      // an emptied box shows Home (its own recent searches): no list over it; ↓ asks for it (showRecent)
      _open = false;
      ++_seq;
      _set(Suggestions.none, text);
      return;
    }
    _open = true;
    _timer = Timer(debounce, () => unawaited(_ask(text)));
  }

  /// The box got focus while empty (or ↓ in an empty box): the recent questions.
  void showRecent() {
    _open = true;
    _hi = -1;
    unawaited(_ask(''));
  }

  Future<void> _ask(String text) async {
    final my = ++_seq;
    Suggestions s;
    try {
      s = await engine.suggest(text, channel: channel);
    } on Object {
      s = Suggestions.none; // never in the way of typing
    }
    if (_disposed || my != _seq) return;
    _set(s, text);
  }

  void _set(Suggestions s, String text) {
    _s = s;
    _for = text;
    if (_hi >= items.length) _hi = -1;
    if (!_disposed) notifyListeners();
  }

  /// The list sits between the box and the results, so the keys walk through it in that order:
  /// ↑ on the first result (or with no results) comes up into the list's last row, ↑ goes on up to its first;
  /// ↓ goes down and, past its last row, back to the results (none highlighted: Enter opens the best guess).
  /// False when the key isn't the list's (the results move as before).
  bool down({bool noResults = false}) {
    if (!isOpen) return false;
    if (_hi < 0) {
      if (!noResults) return false;
      _hi = 0;
    } else {
      _hi = _hi + 1 >= items.length ? -1 : _hi + 1;
    }
    notifyListeners();
    return true;
  }

  /// [atTop]: the first result is selected (or there are none).
  bool up({required bool atTop}) {
    if (!isOpen) return false;
    if (_hi < 0) {
      if (!atTop) return false;
      _hi = items.length - 1;
    } else if (_hi > 0) {
      _hi--;
    }
    notifyListeners();
    return true;
  }

  void hover(int i) {
    if (i == _hi || i < -1 || i >= items.length) return;
    _hi = i;
    notifyListeners();
  }

  /// Esc: closes the list; false when it was already closed.
  bool close() {
    _timer?.cancel();
    final was = isOpen;
    _open = false;
    _hi = -1;
    if (was) notifyListeners();
    return was;
  }

  /// The x on a history row: the engine forgets it, the row goes now.
  Future<void> forget(Suggestion s) async {
    _s = Suggestions(
      items: [
        for (final i in items)
          if (!identical(i, s)) i,
      ],
      complete: _s.complete,
    );
    if (_s.complete.toLowerCase() == s.text.toLowerCase()) _s = Suggestions(items: _s.items);
    if (_hi >= items.length) _hi = items.length - 1;
    notifyListeners();
    try {
      await engine.historyForget(s.text);
    } on Object {
      // offline: it stays forgotten on screen; the engine still has it
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}
