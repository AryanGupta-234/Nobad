/// What is indexed, and the turbo index (contract additions: `scope_info`, `turbo_state`, `turbo_set`, the `turbo`
/// event; settings `scope`, `include_system`, `include_caches`, `include_secrets`, read-only `turbo`).
/// Every name, reason and example path is untrusted text from the engine: shown as plain text.
library;

import 'json.dart';

enum IndexScope {
  wholePc('whole_pc', 'Whole PC'),
  myFiles('my_files', 'My files'),
  custom('custom', 'Custom');

  const IndexScope(this.wire, this.label);
  final String wire;
  final String label;

  static IndexScope? parse(Object? v) => values.where((s) => s.wire == v).firstOrNull;
}

/// One kind of place, listed so nothing is skipped silently.
class ScopeCategory {
  const ScopeCategory({
    required this.id,
    this.name = '',
    this.why = '',
    this.examples = const [],
    this.included = false,
    this.locked = false,
    this.count,
  });

  /// system | caches | secrets | other_profiles | removable | network (others from a newer engine: shown, no switch).
  final String id;
  final String name;
  final String why;
  final List<String> examples;
  final bool included;
  final bool locked;

  /// Entries of it in the index; null when it can't be counted cheaply.
  final int? count;

  /// The setting its switch changes ('' = none this UI knows).
  String get setting =>
      const {
        'system': 'include_system',
        'caches': 'include_caches',
        'secrets': 'include_secrets',
        'removable': 'index_removable',
        'network': 'index_network',
      }[id] ??
      '';

  static ScopeCategory? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['id']).isEmpty) return null;
    return ScopeCategory(
      id: jStr(m['id']),
      name: jStr(m['name']),
      why: jStr(m['why']),
      examples: jStrs(m['examples']),
      included: jBool(m['included']),
      locked: jBool(m['locked']),
      count: jIntOrNull(m['count']),
    );
  }
}

class ScopeInfo {
  const ScopeInfo({this.scope, this.roots = const [], this.categories = const []});
  final IndexScope? scope;
  final List<String> roots;
  final List<ScopeCategory> categories;

  static ScopeInfo fromJson(Object? v) {
    final m = jMap(v);
    return ScopeInfo(
      scope: IndexScope.parse(m['scope']),
      roots: jStrs(m['roots']),
      categories: jList(m['categories'], ScopeCategory.fromJson),
    );
  }
}

class TurboVolume {
  const TurboVolume({required this.drive, this.ntfs = false, this.files = 0, this.usnOk = false, this.lastScan});
  final String drive;
  final bool ntfs;
  final int files;

  /// Changes on the drive come from its change journal.
  final bool usnOk;

  /// Seconds since 1970, or null (not read yet).
  final double? lastScan;

  static TurboVolume? fromJson(Object? v) {
    final m = jMap(v);
    if (jStr(m['drive']).isEmpty) return null;
    final t = m['last_scan'];
    return TurboVolume(
      drive: jStr(m['drive']),
      ntfs: jBool(m['ntfs']),
      files: jInt(m['files']),
      usnOk: jBool(m['usn_ok']),
      lastScan: t is num ? t.toDouble() : null,
    );
  }
}

class TurboState {
  const TurboState({
    this.available = false,
    this.enabled = false,
    this.running = false,
    this.volumes = const [],
    this.error = '',
  });

  /// An NTFS fixed drive is there.
  final bool available;

  /// The `turbo` setting.
  final bool enabled;

  /// The elevated helper is connected.
  final bool running;
  final List<TurboVolume> volumes;

  /// '' or why it isn't running (the normal folder walk is used then).
  final String error;

  /// "Turbo: on (C: NTFS)", or why it is off: the Index page's line.
  String get line {
    if (running) {
      final d = [
        for (final v in volumes)
          if (v.ntfs) v.drive,
      ];
      return 'Turbo: on${d.isEmpty ? '' : ' (${d.join(', ')} NTFS)'}';
    }
    if (error.isNotEmpty) return 'Turbo: off. $error';
    if (!available) return 'Turbo: not available (no NTFS fixed drive)';
    if (enabled) return 'Turbo: starting';
    return 'Turbo: off (Settings → What to index)';
  }

  static TurboState fromJson(Object? v) {
    final m = jMap(v);
    return TurboState(
      available: jBool(m['available']),
      enabled: jBool(m['enabled']),
      running: jBool(m['running']),
      volumes: jList(m['volumes'], TurboVolume.fromJson),
      error: jStr(m['error']),
    );
  }
}

/// `turbo_set` answer.
class TurboSet {
  const TurboSet(this.ok, {this.error = '', this.state});
  final bool ok;
  final String error;
  final TurboState? state;

  static TurboSet fromJson(Object? v) {
    final m = jMap(v);
    return TurboSet(
      jBool(m['ok']),
      error: jStr(m['error']),
      state: m['state'] is Map ? TurboState.fromJson(m['state']) : null,
    );
  }
}
