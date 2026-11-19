/// Numbers into words, with the same steps as the 0.7.0 page (app.js), so the copy reads the same.
library;

/// 12345 -> "12,345".
String groupDigits(int n) {
  final neg = n < 0;
  final s = n.abs().toString();
  final b = StringBuffer(neg ? '-' : '');
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write(',');
    b.write(s[i]);
  }
  return b.toString();
}

double _fin(num? v) => v != null && v.isFinite ? v.toDouble() : 0;

/// Megabytes: "3.2 MB", "42 MB", "512 MB", "2.0 GB".
String mb(num? v) {
  final n = _fin(v);
  if (n >= 1024) return '${(n / 1024).toStringAsFixed(1)} GB';
  return '${n >= 100 ? n.round() : n.toStringAsFixed(n < 10 ? 1 : 0)} MB';
}

/// Gigabytes for the hardware tiles: "15.7 GB", "512 GB", "–".
String gb(num? v) {
  final n = _fin(v);
  if (n == 0) return '–';
  return '${n >= 100 ? n.round() : n.toStringAsFixed(1).replaceAll(RegExp(r'\.0$'), '')} GB';
}

/// "12 KB", "3.4 MB" for file sizes (bytes).
String humanSize(int? n) {
  if (n == null || n <= 0) return '';
  if (n < 1024) return '$n B';
  if (n < 1 << 20) return '${(n / 1024).toStringAsFixed(0)} KB';
  if (n < 1 << 30) return '${(n / 1048576).toStringAsFixed(1)} MB';
  return '${(n / 1073741824).toStringAsFixed(2)} GB';
}

/// A rough time span: "under a minute", "about 10 min", "about 2 h", "about 3 days".
String span(num seconds) {
  final sec = _fin(seconds).round().clamp(0, 1 << 40);
  if (sec < 45) return 'under a minute';
  if (sec < 5400) return 'about ${(sec / 60).round().clamp(1, 1 << 30)} min';
  if (sec < 172800) return 'about ${(sec / 3600).round()} h';
  return 'about ${(sec / 86400).round()} days';
}

/// "12 files per second", "2.3 files per second", "6 files per minute", or "".
String perTime(num? rate, String unit) {
  final r = _fin(rate);
  if (r <= 0) return '';
  if (r >= 1) return '${r >= 10 ? r.round() : r.toStringAsFixed(1)} $unit per second';
  return '${(r * 60).round().clamp(1, 1 << 30)} $unit per minute';
}

/// "13%", or "–" when unknown.
String pct(num? v) => v == null || !v.isFinite ? '–' : '${v.round()}%';

/// "14:05" (24 h, like toLocaleTimeString with 2-digit hours and minutes) for an epoch in seconds.
String clock(num t) {
  final ms = t < 1e11 ? t * 1000 : t;
  if (!ms.isFinite) return '';
  final d = DateTime.fromMillisecondsSinceEpoch(ms.round());
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(d.hour)}:${two(d.minute)}';
}
