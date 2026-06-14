import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_client.dart';
import '../core/api/api_endpoints.dart';
import '../core/models/story.dart';
import 'core_providers.dart';

/// Data operations for STORIES (films + series).
class StoriesRepository {
  /// Creates the repository.
  StoriesRepository(this._api);
  final ApiClient _api;

  /// `GET /api/stories` → the full library.
  Future<StoriesLibrary> fetchLibrary() async {
    final data = await _api.get(ApiEndpoints.stories);
    return StoriesLibrary.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// `GET /api/stories/films/{id}` → FilmDetail.
  Future<Film> fetchFilm(String id) async {
    final data = await _api.get(ApiEndpoints.storyFilm(id));
    return Film.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// `GET /api/stories/series/{id}` (+ episodes) → a fully-populated [Series].
  Future<Series> fetchSeries(String id) async {
    final detail = await _api.get(ApiEndpoints.storySeries(id));
    final series = Series.fromJson(Map<String, dynamic>.from(detail as Map));
    final eps = await fetchEpisodes(id);
    return series.withEpisodes(eps);
  }

  /// `GET /api/stories/series/{id}/episodes` → ordered episodes.
  Future<List<Episode>> fetchEpisodes(String id) async {
    final data = await _api.get(ApiEndpoints.storySeriesEpisodes(id));
    final list = data is List ? data : const [];
    return list
        .whereType<Map>()
        .map((e) => Episode.fromJson(Map<String, dynamic>.from(e)))
        .toList()
      ..sort((a, b) {
        final s = a.seasonNumber.compareTo(b.seasonNumber);
        return s != 0 ? s : a.number.compareTo(b.number);
      });
  }

  /// `GET /api/stories/search?q=` → `{films, series}`.
  Future<({List<Film> films, List<Series> series})> search(String q) async {
    final data = await _api.get(ApiEndpoints.storiesSearch, query: {'q': q});
    final map = Map<String, dynamic>.from(data as Map);
    final films = (map['films'] is List ? map['films'] as List : const [])
        .whereType<Map>()
        .map((e) => Film.fromJson(Map<String, dynamic>.from(e)))
        .toList();
    final series = (map['series'] is List ? map['series'] as List : const [])
        .whereType<Map>()
        .map((e) => Series.fromJson(Map<String, dynamic>.from(e)))
        .toList();
    return (films: films, series: series);
  }

  /// `POST /api/stories/progress` — records watch position.
  Future<void> postProgress({
    required String contentType, // 'film' | 'episode'
    required String contentId,
    required int positionSeconds,
    int? durationSeconds,
  }) =>
      _api.post(ApiEndpoints.storiesProgress, body: {
        'content_type': contentType,
        'content_id': contentId,
        'position_seconds': positionSeconds,
        if (durationSeconds != null) 'duration_seconds': durationSeconds,
      });

  /// `POST /api/stories/like` — toggles a like.
  Future<void> postLike({
    required String contentType, // 'film' | 'series' | 'episode'
    required String contentId,
    required bool liked,
  }) =>
      _api.post(ApiEndpoints.storiesLike, body: {
        'content_type': contentType,
        'content_id': contentId,
        'liked': liked,
      });
}

/// STORIES data repository.
final storiesRepositoryProvider =
    Provider<StoriesRepository>((ref) => StoriesRepository(ref.watch(apiClientProvider)));

/// The STORIES library — `GET /api/stories`. Polls while anything is generating.
class StoriesLibraryController extends AsyncNotifier<StoriesLibrary> {
  Timer? _poll;

  @override
  Future<StoriesLibrary> build() async {
    ref.onDispose(() => _poll?.cancel());
    final lib = await ref.read(storiesRepositoryProvider).fetchLibrary();
    _syncPolling(lib);
    return lib;
  }

  /// Pull-to-refresh.
  Future<void> refresh() async {
    state = await AsyncValue.guard(() async {
      final lib = await ref.read(storiesRepositoryProvider).fetchLibrary();
      _syncPolling(lib);
      return lib;
    });
  }

  void _syncPolling(StoriesLibrary lib) {
    final anyProcessing = lib.films.any((f) => f.processing) || lib.series.any((s) => s.processing);
    if (anyProcessing) {
      _poll ??= Timer.periodic(const Duration(seconds: 15), (_) => _tick());
    } else {
      _poll?.cancel();
      _poll = null;
    }
  }

  Future<void> _tick() async {
    try {
      final lib = await ref.read(storiesRepositoryProvider).fetchLibrary();
      state = AsyncData(lib);
      _syncPolling(lib);
    } catch (_) {/* keep last good state; retry next tick */}
  }
}

/// STORIES library provider.
final storiesLibraryProvider =
    AsyncNotifierProvider<StoriesLibraryController, StoriesLibrary>(StoriesLibraryController.new);

/// A single film by id (FilmDetail).
final filmDetailProvider =
    FutureProvider.family<Film, String>((ref, id) => ref.watch(storiesRepositoryProvider).fetchFilm(id));

/// A single series by id, with its episodes attached.
final seriesDetailProvider =
    FutureProvider.family<Series, String>((ref, id) => ref.watch(storiesRepositoryProvider).fetchSeries(id));

/// A series' episodes by series id.
final seriesEpisodesProvider =
    FutureProvider.family<List<Episode>, String>((ref, id) => ref.watch(storiesRepositoryProvider).fetchEpisodes(id));

/// STORIES search results for a query.
final storiesSearchProvider =
    FutureProvider.family<({List<Film> films, List<Series> series}), String>(
        (ref, q) => ref.watch(storiesRepositoryProvider).search(q));
