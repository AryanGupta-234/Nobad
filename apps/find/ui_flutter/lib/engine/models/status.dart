/// The engine's short status (`status` method and the `status` event; Api.status_brief in Python).
library;

class EngineStatus {
  const EngineStatus({this.level = '', this.reason = '', this.phase = '', this.files = 0, this.paused = ''});

  final String level;
  final String reason;
  final String phase;
  final int files;
  final String paused;

  static EngineStatus fromJson(Object? json) {
    if (json is! Map) return const EngineStatus();
    String s(String k) => json[k] is String ? json[k] as String : '';
    final f = json['files'];
    return EngineStatus(level: s('level'), reason: s('reason'), phase: s('phase'), paused: s('paused'),
        files: f is int && f >= 0 ? f : 0);
  }

  /// Same words as the 0.7.0 page.
  static const phaseLabels = {
    'starting': 'Starting', 'names': 'Finding files', 'text': 'Reading text', 'images': 'Reading photos and scans',
    'photos': 'Understanding photos', 'meaning': 'Learning meaning', 'watching': 'Up to date', 'error': 'Stopped',
  };
  static const levelLabels = {
    'full': 'Working at full speed', 'gentle': 'Working gently', 'light': 'Working very lightly', 'paused': 'Paused',
  };

  String get phaseLabel => paused.isNotEmpty ? 'Paused · $paused' : (phaseLabels[phase] ?? phase);
  String get levelLabel => levelLabels[level] ?? '';

  @override
  bool operator ==(Object other) =>
      other is EngineStatus && other.level == level && other.reason == reason && other.phase == phase &&
      other.files == files && other.paused == paused;

  @override
  int get hashCode => Object.hash(level, reason, phase, files, paused);
}

/// 12345 -> "12,345".
String groupDigits(int n) {
  final s = n.toString();
  final b = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
    b.write(s[i]);
  }
  return b.toString();
}
