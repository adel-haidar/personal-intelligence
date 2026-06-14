import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_endpoints.dart';
import '../core/models/paginated.dart';
import '../core/models/video.dart';
import 'core_providers.dart';

/// Loads the SIGNAL video grid and polls while any video is still rendering.
///
/// There is no `/api/signal/status` endpoint, so "polling" re-fetches the first
/// page of `/content/videos` every 15s and stops once nothing is processing.
class SignalController extends AsyncNotifier<List<Video>> {
  Timer? _poll;

  @override
  Future<List<Video>> build() async {
    ref.onDispose(() => _poll?.cancel());
    final videos = await _fetch();
    _syncPolling(videos);
    return videos;
  }

  Future<List<Video>> _fetch() async {
    final data = await ref.read(apiClientProvider).get(
      ApiEndpoints.videos,
      query: {'page': 1, 'page_size': 50},
    );
    final paged = Paginated.fromJson(Map<String, dynamic>.from(data as Map), Video.fromJson);
    return paged.items;
  }

  /// Manual refresh (pull-to-refresh).
  Future<void> refresh() async {
    state = await AsyncValue.guard(() async {
      final v = await _fetch();
      _syncPolling(v);
      return v;
    });
  }

  void _syncPolling(List<Video> videos) {
    final anyProcessing = videos.any((v) => v.isProcessing);
    if (anyProcessing) {
      _poll ??= Timer.periodic(const Duration(seconds: 15), (_) => _tick());
    } else {
      _poll?.cancel();
      _poll = null;
    }
  }

  Future<void> _tick() async {
    try {
      final videos = await _fetch();
      state = AsyncData(videos);
      _syncPolling(videos);
    } catch (_) {/* keep last good state; try again next tick */}
  }

  /// Logs a like/dislike against a video.
  Future<void> react(String videoId, {required bool like}) =>
      ref.read(apiClientProvider).post(
        ApiEndpoints.interactions,
        body: {'content_id': videoId, 'content_type': 'video', 'action': like ? 'like' : 'dislike'},
      );

  /// Records that a video was watched (used by the player on completion).
  Future<void> markWatched(String videoId, {double pct = 1.0}) =>
      ref.read(apiClientProvider).post(
        ApiEndpoints.interactions,
        body: {
          'content_id': videoId,
          'content_type': 'video',
          'action': pct >= 0.95 ? 'watch_complete' : 'watch_partial',
          'watch_pct': pct.clamp(0.0, 1.0),
        },
      );
}

/// SIGNAL videos provider.
final signalProvider = AsyncNotifierProvider<SignalController, List<Video>>(SignalController.new);

/// A single video by id, resolved from the loaded grid (no per-id endpoint).
final videoByIdProvider = Provider.family<Video?, String>((ref, id) {
  final videos = ref.watch(signalProvider).valueOrNull ?? const [];
  for (final v in videos) {
    if (v.id == id) return v;
  }
  return null;
});
