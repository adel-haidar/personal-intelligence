import 'json_utils.dart';

/// Daily health metrics (`/health/summary/{date}` → `DailyHealthSummary`, also
/// embedded as `summary` in the insight response).
class HealthSummary {
  /// Constructs a summary.
  const HealthSummary({
    this.weightKg,
    this.weight7DayAvg,
    this.weightTrendKgPerWeek,
    this.bodyFatPercent,
    this.restingHr,
    this.restingHr7DayAvg,
    this.hrvMs,
    this.sleepDurationMin,
    this.sleepScore,
    this.steps,
    this.activeEnergyKcal,
    this.progressToGoalKg,
    this.weeksToGoalAtCurrentRate,
  });

  final double? weightKg;
  final double? weight7DayAvg;
  final double? weightTrendKgPerWeek;
  final double? bodyFatPercent;
  final double? restingHr;
  final double? restingHr7DayAvg;
  final double? hrvMs;
  final double? sleepDurationMin;
  final double? sleepScore;
  final int? steps;
  final double? activeEnergyKcal;
  final double? progressToGoalKg;
  final double? weeksToGoalAtCurrentRate;

  /// Decodes a summary.
  factory HealthSummary.fromJson(Map<String, dynamic> json) => HealthSummary(
        weightKg: asDouble(json['weight_kg']),
        weight7DayAvg: asDouble(json['weight_7day_avg']),
        weightTrendKgPerWeek: asDouble(json['weight_trend_kg_per_week']),
        bodyFatPercent: asDouble(json['body_fat_percent']),
        restingHr: asDouble(json['resting_hr']),
        restingHr7DayAvg: asDouble(json['resting_hr_7day_avg']),
        hrvMs: asDouble(json['hrv_ms']),
        sleepDurationMin: asDouble(json['sleep_duration_min']),
        sleepScore: asDouble(json['sleep_score']),
        steps: asInt(json['steps']),
        activeEnergyKcal: asDouble(json['active_energy_kcal']),
        progressToGoalKg: asDouble(json['progress_to_goal_kg']),
        weeksToGoalAtCurrentRate: asDouble(json['weeks_to_goal_at_current_rate']),
      );

  /// True when there is no usable data for the day.
  bool get isEmpty =>
      weightKg == null && restingHr == null && steps == null && sleepDurationMin == null;

  /// Sleep duration rendered as "7h 24m", or null.
  String? get sleepLabel {
    final m = sleepDurationMin;
    if (m == null) return null;
    return '${(m ~/ 60)}h ${(m % 60).round()}m';
  }
}

/// The narrative insight bundle (`/health/daily/{date}`, `/health/run-daily`).
class HealthInsight {
  /// Constructs an insight.
  const HealthInsight({
    this.date,
    this.summary,
    this.flags = const [],
    this.coachInsight = '',
    this.analysis = '',
    this.reasoning = '',
    this.documents = const [],
  });

  final String? date;
  final HealthSummary? summary;
  final List<String> flags;
  final String coachInsight;
  final String analysis;
  final String reasoning;
  final List<String> documents;

  /// Decodes an insight response.
  factory HealthInsight.fromJson(Map<String, dynamic> json) {
    final rawSummary = json['summary'];
    return HealthInsight(
      date: asStrOrNull(json['date']),
      summary: rawSummary is Map ? HealthSummary.fromJson(Map<String, dynamic>.from(rawSummary)) : null,
      flags: asStrList(json['flags']),
      coachInsight: asStr(json['coach_insight']),
      analysis: asStr(json['analysis']),
      reasoning: asStr(json['reasoning']),
      documents: asStrList(json['documents']),
    );
  }
}
