/// Defensive JSON coercion helpers used by every `fromJson` in the model layer.
///
/// The backend returns flat dynamic rows (psycopg2 `RealDictRow`), so numbers
/// may arrive as int, double, or numeric string. These helpers never throw.
library;

/// Coerces [v] to a non-null [String], or [fallback] if null.
String asStr(Object? v, [String fallback = '']) => v?.toString() ?? fallback;

/// Coerces [v] to a nullable [String].
String? asStrOrNull(Object? v) => v?.toString();

/// Coerces [v] to a nullable [double] (handles int / String / num).
double? asDouble(Object? v) {
  if (v == null) return null;
  if (v is num) return v.toDouble();
  return double.tryParse(v.toString());
}

/// Coerces [v] to a nullable [int].
int? asInt(Object? v) {
  if (v == null) return null;
  if (v is int) return v;
  if (v is num) return v.toInt();
  return int.tryParse(v.toString());
}

/// Coerces [v] to a [bool] (handles bool / 1 / "true").
bool asBool(Object? v, [bool fallback = false]) {
  if (v is bool) return v;
  if (v is num) return v != 0;
  if (v is String) return v.toLowerCase() == 'true' || v == '1';
  return fallback;
}

/// Parses an ISO-8601 timestamp string, tolerating null/garbage.
DateTime? asDate(Object? v) {
  if (v == null) return null;
  return DateTime.tryParse(v.toString())?.toLocal();
}

/// Coerces [v] to a `List<String>`, accepting a list or a comma-joined string.
List<String> asStrList(Object? v) {
  if (v == null) return const [];
  if (v is List) return v.map((e) => e.toString()).toList();
  if (v is String) {
    return v.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();
  }
  return const [];
}
