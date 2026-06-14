/// STORIES domain models — long-form cinema (films + multi-episode series).
///
/// Plain immutable classes (no freezed) mapped to the real `/api/stories`
/// backend shapes (FilmSummary / FilmDetail / SeriesSummary / EpisodeSummary).
/// The backend exposes NO genre, score, year, topics, or "why" — those fields
/// were removed; the UI degrades accordingly. `category` is the only discovery
/// axis and is rendered as the old "genre" chip.
library;

import 'json_utils.dart';

/// Processing state of a film / series / episode (`status` column).
enum StoryStatus {
  /// Still being generated.
  generating,

  /// Ready to play.
  ready,

  /// Generation failed.
  failed,
}

StoryStatus _storyStatus(String raw) {
  switch (raw.toLowerCase()) {
    case 'ready':
    case 'complete':
    case 'completed':
    case 'done':
      return StoryStatus.ready;
    case 'failed':
    case 'error':
      return StoryStatus.failed;
    default:
      return StoryStatus.generating;
  }
}

/// Formats whole seconds as `m:ss`, or empty when unknown.
String storyDurationLabel(double? seconds) {
  final s = seconds?.round();
  if (s == null || s <= 0) return '';
  final m = s ~/ 60;
  final r = s % 60;
  return '$m:${r.toString().padLeft(2, '0')}';
}

/// Watch progress for a film or episode.
class WatchProgress {
  /// Creates watch progress.
  const WatchProgress({
    required this.positionSeconds,
    required this.durationSeconds,
    required this.completed,
  });

  final double positionSeconds;
  final double? durationSeconds;
  final bool completed;

  /// Decodes a `watch_progress` / `continue_watching` sub-object.
  factory WatchProgress.fromJson(Map<String, dynamic> json) => WatchProgress(
        positionSeconds: asDouble(json['position_seconds']) ?? 0,
        durationSeconds: asDouble(json['duration_seconds']),
        completed: asBool(json['completed']),
      );

  /// 0–100 progress, or null when the total duration is unknown / zero.
  int? get percent {
    final d = durationSeconds;
    if (d == null || d <= 0) return null;
    return ((positionSeconds / d) * 100).clamp(0, 100).round();
  }

  /// "15m left" label, or empty when total duration is unknown.
  String get leftLabel {
    final d = durationSeconds;
    if (d == null || d <= 0) return '';
    final left = (d - positionSeconds).clamp(0, d);
    final mins = (left / 60).round();
    return '${mins}m left';
  }

  /// `mm:ss` resume position label.
  String get resumeLabel => storyDurationLabel(positionSeconds);
}

/// A single film. FilmSummary, optionally enriched to FilmDetail.
class Film {
  /// Creates a film.
  const Film({
    required this.id,
    required this.title,
    this.premise,
    this.category,
    this.thumbnailUrl,
    this.posterUrl,
    this.durationSeconds,
    this.status = StoryStatus.ready,
    // FilmDetail-only fields.
    this.videoUrl,
    this.signalVideoId,
    this.watchProgress,
    this.related = const [],
    this.liked = false,
  });

  final String id;
  final String title;

  /// Lora premise paragraph (nullable on the backend).
  final String? premise;

  /// Topic-cluster category, e.g. `Finance`. The only discovery axis.
  final String? category;

  final String? thumbnailUrl;
  final String? posterUrl;

  /// Duration in seconds (float on the backend).
  final double? durationSeconds;
  final StoryStatus status;

  // ---- FilmDetail-only ----
  final String? videoUrl;
  final String? signalVideoId;
  final WatchProgress? watchProgress;
  final List<Film> related;
  final bool liked;

  /// `mm:ss` duration label, or empty when unknown.
  String get duration => storyDurationLabel(durationSeconds);

  /// True while the film is still being generated.
  bool get processing => status == StoryStatus.generating;

  /// Short category chip label (uppercase, ≤8 chars), or null.
  String? get categoryChip {
    final cat = category;
    if (cat == null || cat.isEmpty) return null;
    final up = cat.toUpperCase();
    return up.length > 8 ? up.substring(0, 8) : up;
  }

  /// Whether watching has started (some progress recorded, not finished).
  bool get started {
    final p = watchProgress?.percent;
    return p != null && p > 0 && !(watchProgress?.completed ?? false);
  }

  /// Decodes a FilmSummary or FilmDetail row.
  factory Film.fromJson(Map<String, dynamic> json) {
    final wp = json['watch_progress'];
    final rel = json['related'];
    return Film(
      id: asStr(json['id']),
      title: asStr(json['title']),
      premise: asStrOrNull(json['premise']),
      category: asStrOrNull(json['category']),
      thumbnailUrl: asStrOrNull(json['thumbnail_url']),
      posterUrl: asStrOrNull(json['poster_url']),
      durationSeconds: asDouble(json['duration_seconds']),
      status: _storyStatus(asStr(json['status'], 'ready')),
      videoUrl: asStrOrNull(json['video_url']),
      signalVideoId: asStrOrNull(json['signal_video_id']),
      watchProgress: wp is Map ? WatchProgress.fromJson(Map<String, dynamic>.from(wp)) : null,
      related: rel is List
          ? rel.whereType<Map>().map((e) => Film.fromJson(Map<String, dynamic>.from(e))).toList()
          : const [],
      liked: asBool(json['liked']),
    );
  }
}

/// An episode within a [Series]. EpisodeSummary.
class Episode {
  /// Creates an episode.
  const Episode({
    required this.id,
    required this.seriesId,
    required this.seasonNumber,
    required this.number,
    required this.title,
    this.premise,
    this.videoUrl,
    this.thumbnailUrl,
    this.durationSeconds,
    this.status = StoryStatus.ready,
  });

  final String id;
  final String seriesId;
  final int seasonNumber;

  /// Episode number within the season.
  final int number;
  final String title;
  final String? premise;
  final String? videoUrl;
  final String? thumbnailUrl;
  final double? durationSeconds;
  final StoryStatus status;

  /// `mm:ss` duration label, or empty.
  String get duration => storyDurationLabel(durationSeconds);

  /// True while still generating.
  bool get processing => status == StoryStatus.generating;

  /// Decodes an EpisodeSummary row.
  factory Episode.fromJson(Map<String, dynamic> json) => Episode(
        id: asStr(json['id']),
        seriesId: asStr(json['series_id']),
        seasonNumber: asInt(json['season_number']) ?? 1,
        number: asInt(json['episode_number']) ?? 1,
        title: asStr(json['title']),
        premise: asStrOrNull(json['premise']),
        videoUrl: asStrOrNull(json['video_url']),
        thumbnailUrl: asStrOrNull(json['thumbnail_url']),
        durationSeconds: asDouble(json['duration_seconds']),
        status: _storyStatus(asStr(json['status'], 'ready')),
      );
}

/// A multi-episode series — presented as a "box set". SeriesSummary, optionally
/// carrying its [episodes] once loaded.
class Series {
  /// Creates a series.
  const Series({
    required this.id,
    required this.title,
    this.premise,
    this.category,
    this.thumbnailUrl,
    this.posterUrl,
    this.status = StoryStatus.ready,
    this.episodeCount = 0,
    this.liked = false,
    this.episodes = const [],
  });

  final String id;
  final String title;
  final String? premise;
  final String? category;
  final String? thumbnailUrl;
  final String? posterUrl;
  final StoryStatus status;

  /// Episode count from the detail endpoint (0 from list summaries).
  final int episodeCount;
  final bool liked;

  /// Loaded episodes (empty until the episodes endpoint is fetched).
  final List<Episode> episodes;

  /// True while still generating.
  bool get processing => status == StoryStatus.generating;

  /// Short category chip label (uppercase, ≤8 chars), or null.
  String? get categoryChip {
    final cat = category;
    if (cat == null || cat.isEmpty) return null;
    final up = cat.toUpperCase();
    return up.length > 8 ? up.substring(0, 8) : up;
  }

  /// Effective episode count (loaded list takes precedence).
  int get effectiveEpisodeCount => episodes.isNotEmpty ? episodes.length : episodeCount;

  /// Returns a copy with [episodes] attached.
  Series withEpisodes(List<Episode> eps) => Series(
        id: id,
        title: title,
        premise: premise,
        category: category,
        thumbnailUrl: thumbnailUrl,
        posterUrl: posterUrl,
        status: status,
        episodeCount: eps.isNotEmpty ? eps.length : episodeCount,
        liked: liked,
        episodes: eps,
      );

  /// Decodes a SeriesSummary / series-detail row (episodes attached separately).
  factory Series.fromJson(Map<String, dynamic> json) => Series(
        id: asStr(json['id']),
        title: asStr(json['title']),
        premise: asStrOrNull(json['premise']),
        category: asStrOrNull(json['category']),
        thumbnailUrl: asStrOrNull(json['thumbnail_url']),
        posterUrl: asStrOrNull(json['poster_url']),
        status: _storyStatus(asStr(json['status'], 'ready')),
        episodeCount: asInt(json['episode_count']) ?? 0,
        liked: asBool(json['liked']),
      );
}

/// A topic-cluster category with its content counts (`GET /categories`).
class StoryCategory {
  /// Creates a category.
  const StoryCategory({required this.name, this.filmCount = 0, this.seriesCount = 0});

  final String name;
  final int filmCount;
  final int seriesCount;

  /// Decodes a category row.
  factory StoryCategory.fromJson(Map<String, dynamic> json) => StoryCategory(
        name: asStr(json['category']),
        filmCount: asInt(json['film_count']) ?? 0,
        seriesCount: asInt(json['series_count']) ?? 0,
      );
}

/// A "continue watching" entry (`continue_watching[]` in the library response).
class ContinueWatching {
  /// Creates a continue-watching entry.
  const ContinueWatching({
    required this.contentType,
    required this.contentId,
    required this.title,
    this.thumbnailUrl,
    required this.positionSeconds,
    this.durationSeconds,
    this.completed = false,
  });

  /// 'film' or 'episode'.
  final String contentType;
  final String contentId;
  final String title;
  final String? thumbnailUrl;
  final double positionSeconds;
  final double? durationSeconds;
  final bool completed;

  /// True when this entry is a series episode.
  bool get isEpisode => contentType == 'episode';

  /// 0–100 progress, or null when total duration is unknown.
  int? get percent {
    final d = durationSeconds;
    if (d == null || d <= 0) return null;
    return ((positionSeconds / d) * 100).clamp(0, 100).round();
  }

  /// "15m left" label, or empty.
  String get leftLabel {
    final d = durationSeconds;
    if (d == null || d <= 0) return '';
    final left = (d - positionSeconds).clamp(0, d);
    return '${(left / 60).round()}m left';
  }

  /// Decodes a continue-watching entry.
  factory ContinueWatching.fromJson(Map<String, dynamic> json) => ContinueWatching(
        contentType: asStr(json['content_type']),
        contentId: asStr(json['content_id']),
        title: asStr(json['title']),
        thumbnailUrl: asStrOrNull(json['thumbnail_url']),
        positionSeconds: asDouble(json['position_seconds']) ?? 0,
        durationSeconds: asDouble(json['duration_seconds']),
        completed: asBool(json['completed']),
      );
}

/// The STORIES library response (`GET /api/stories`).
class StoriesLibrary {
  /// Creates a library snapshot.
  const StoriesLibrary({
    this.films = const [],
    this.series = const [],
    this.categories = const [],
    this.continueWatching = const [],
  });

  final List<Film> films;
  final List<Series> series;
  final List<StoryCategory> categories;
  final List<ContinueWatching> continueWatching;

  /// The featured film (first ready film, else first film, else null).
  Film? get featured {
    for (final f in films) {
      if (!f.processing) return f;
    }
    return films.isEmpty ? null : films.first;
  }

  /// Decodes the library response.
  factory StoriesLibrary.fromJson(Map<String, dynamic> json) {
    List<T> list<T>(Object? v, T Function(Map<String, dynamic>) fromJson) =>
        v is List ? v.whereType<Map>().map((e) => fromJson(Map<String, dynamic>.from(e))).toList() : <T>[];
    return StoriesLibrary(
      films: list(json['films'], Film.fromJson),
      series: list(json['series'], Series.fromJson),
      categories: list(json['categories'], StoryCategory.fromJson),
      continueWatching: list(json['continue_watching'], ContinueWatching.fromJson),
    );
  }
}
