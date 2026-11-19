/// Lenient readers for engine JSON: a missing or odd value becomes a safe default, never an exception or NaN.
library;

String jStr(Object? v) => v is String ? v : '';
int jInt(Object? v, [int fallback = 0]) => v is int ? v : (v is double && v.isFinite ? v.round() : fallback);
int? jIntOrNull(Object? v) => v is int ? v : (v is double && v.isFinite ? v.round() : null);
double jNum(Object? v, [double fallback = 0]) => v is num && v.isFinite ? v.toDouble() : fallback;
double? jNumOrNull(Object? v) => v is num && v.isFinite ? v.toDouble() : null;
bool jBool(Object? v) => v == true;
List<String> jStrs(Object? v) => v is List
    ? [
        for (final x in v)
          if (x is String) x,
      ]
    : const [];
Map<String, Object?> jMap(Object? v) => v is Map
    ? {
        for (final e in v.entries)
          if (e.key is String) e.key as String: e.value,
      }
    : const {};
List<T> jList<T>(Object? v, T? Function(Object?) parse) => v is List ? [for (final x in v) ?parse(x)] : const [];
