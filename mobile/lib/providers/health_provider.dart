import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../core/api/api_endpoints.dart';
import '../core/models/health.dart';
import 'core_providers.dart';

/// Today's health insight + summary, with a 30s refresh poll while the screen
/// is active (there is no live sync-status endpoint, so we re-pull `/daily`).
class HealthController extends AsyncNotifier<HealthInsight> {
  Timer? _poll;

  String get _today => DateFormat('yyyy-MM-dd').format(DateTime.now());

  @override
  Future<HealthInsight> build() async {
    ref.onDispose(() => _poll?.cancel());
    return _load();
  }

  Future<HealthInsight> _load() async {
    final api = ref.read(apiClientProvider);
    // `/daily/{date}` returns the full narrative + embedded summary.
    final data = await api.get(ApiEndpoints.healthDaily(_today));
    final insight = HealthInsight.fromJson(Map<String, dynamic>.from(data as Map));
    if (insight.summary != null) return insight;
    // Fall back to the bare summary endpoint if the narrative has no metrics yet.
    try {
      final s = await api.get(ApiEndpoints.healthSummary(_today));
      return HealthInsight(
        date: _today,
        summary: HealthSummary.fromJson(Map<String, dynamic>.from(s as Map)),
        flags: insight.flags,
        coachInsight: insight.coachInsight,
        analysis: insight.analysis,
        reasoning: insight.reasoning,
        documents: insight.documents,
      );
    } catch (_) {
      return insight;
    }
  }

  /// Pull-to-refresh.
  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(_load);
  }

  /// Starts the 30s active-screen poll.
  void startPolling() {
    _poll ??= Timer.periodic(const Duration(seconds: 30), (_) async {
      final next = await AsyncValue.guard(_load);
      if (next is AsyncData) state = next;
    });
  }

  /// Stops polling (call on screen dispose / deactivate).
  void stopPolling() {
    _poll?.cancel();
    _poll = null;
  }

  /// Uploads an Apple Health / health export file to be ingested.
  ///
  /// NOTE: the backend's apple-health import expects parsed metrics; a raw file
  /// upload is indexed to the brain via `/file`. We surface upload through the
  /// generic brain file route, then trigger a daily recompute.
  Future<void> recomputeToday() async {
    await ref.read(apiClientProvider).post(ApiEndpoints.healthRunDaily(_today));
    await refresh();
  }
}

/// Today's health provider.
final healthProvider = AsyncNotifierProvider<HealthController, HealthInsight>(HealthController.new);

/// Weight trend points (`/health/trends`) for the detailed chart.
final healthTrendsProvider = FutureProvider<List<MapEntry<DateTime, double>>>((ref) async {
  final data = await ref.read(apiClientProvider).get(ApiEndpoints.healthTrends);
  // Tolerant parse: accept {weight:[{date,value}]} or a flat list.
  final list = _extractSeries(data, ['weight', 'weight_kg', 'series', 'points']);
  return list;
});

List<MapEntry<DateTime, double>> _extractSeries(Object? data, List<String> keys) {
  List? raw;
  if (data is List) {
    raw = data;
  } else if (data is Map) {
    for (final k in keys) {
      if (data[k] is List) {
        raw = data[k] as List;
        break;
      }
    }
  }
  if (raw == null) return const [];
  final out = <MapEntry<DateTime, double>>[];
  for (final p in raw) {
    if (p is Map) {
      final d = DateTime.tryParse('${p['date'] ?? p['day'] ?? ''}');
      final v = (p['value'] ?? p['weight'] ?? p['weight_kg']);
      final dv = v is num ? v.toDouble() : double.tryParse('$v');
      if (d != null && dv != null) out.add(MapEntry(d, dv));
    }
  }
  out.sort((a, b) => a.key.compareTo(b.key));
  return out;
}
