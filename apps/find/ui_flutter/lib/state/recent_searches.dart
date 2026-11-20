/// Recent searches, kept by the UI in the user's own data folder (never sent anywhere; the engine has no copy):
/// newest first, no repeats, at most 8, cleared with one click.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

class RecentSearches extends ChangeNotifier {
  RecentSearches(this.file);

  /// Null: kept in memory only (tests).
  final File? file;
  static const max = 8;
  List<String> _items = const [];

  List<String> get items => _items;

  /// `%LOCALAPPDATA%\NOBAD\Find\ui-recent.json` (next to the engine's data, only this user can read it).
  static File? defaultFile() {
    final base =
        Platform.environment['NOBAD_FIND_DATA_DIR'] ??
        (Platform.environment['LOCALAPPDATA'] == null ? null : '${Platform.environment['LOCALAPPDATA']}\\NOBAD\\Find');
    return base == null ? null : File('$base\\ui-recent.json');
  }

  Future<void> load() async {
    try {
      final f = file;
      if (f == null || !f.existsSync()) return;
      final v = jsonDecode(await f.readAsString());
      if (v is List) {
        _items = [
          for (final x in v)
            if (x is String && x.trim().isNotEmpty) x,
        ].take(max).toList();
      }
      notifyListeners();
    } on Object {
      // a broken file is just no history
    }
  }

  void add(String words) {
    final w = words.trim();
    if (w.isEmpty) return;
    _items = [
      w,
      for (final x in _items)
        if (x.toLowerCase() != w.toLowerCase()) x,
    ].take(max).toList();
    notifyListeners();
  }

  Future<void> save() async {
    final f = file;
    if (f == null) return;
    try {
      await f.parent.create(recursive: true);
      await f.writeAsString(jsonEncode(_items));
    } on Object {
      // not kept this time
    }
  }

  Future<void> clear() async {
    _items = const [];
    notifyListeners();
    try {
      final f = file;
      if (f != null && f.existsSync()) await f.delete();
    } on Object {
      // nothing more to do
    }
  }
}
