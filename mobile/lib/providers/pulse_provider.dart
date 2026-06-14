import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_client.dart';
import '../core/api/api_endpoints.dart';
import '../core/models/creator.dart';
import '../core/models/paginated.dart';
import '../core/models/post.dart';
import 'core_providers.dart';

/// Sort modes accepted by `/content/posts?sort=`.
enum PostSort {
  /// Newest first.
  latest,

  /// Highest score first.
  top,

  /// Least-rated first.
  unrated,
}

/// Maps a [PostSort] to its API value.
extension PostSortApi on PostSort {
  /// The `sort` query value.
  String get value => switch (this) {
        PostSort.latest => 'latest',
        PostSort.top => 'top',
        PostSort.unrated => 'unrated',
      };

  /// Human label for the filter sheet.
  String get label => switch (this) {
        PostSort.latest => 'Latest',
        PostSort.top => 'Top score',
        PostSort.unrated => 'Unrated',
      };
}

/// The editorial feed filter: a tone chip (client-side), a sort (server-side),
/// and an optional creator (client-side).
class PulseFilter {
  /// Constructs a filter. [tone] is 'all' or a lowercase tone name.
  const PulseFilter({this.tone = 'all', this.sort = PostSort.top, this.creatorId});

  final String tone;
  final PostSort sort;
  final String? creatorId;

  /// Returns a copy with overrides.
  PulseFilter copyWith({String? tone, PostSort? sort, String? creatorId, bool clearCreator = false}) =>
      PulseFilter(
        tone: tone ?? this.tone,
        sort: sort ?? this.sort,
        creatorId: clearCreator ? null : (creatorId ?? this.creatorId),
      );
}

/// Current feed filter.
final pulseFilterProvider = NotifierProvider<PulseFilterController, PulseFilter>(PulseFilterController.new);

/// Holds and mutates [PulseFilter].
class PulseFilterController extends Notifier<PulseFilter> {
  @override
  PulseFilter build() => const PulseFilter();

  /// Sets the active tone chip ('all' or a tone name).
  void setTone(String tone) => state = state.copyWith(tone: tone);

  /// Sets the sort mode (from the filter sheet).
  void setSort(PostSort sort) => state = state.copyWith(sort: sort);

  /// Sets (or clears with null) the creator filter.
  void setCreator(String? creatorId) =>
      state = creatorId == null ? state.copyWith(clearCreator: true) : state.copyWith(creatorId: creatorId);
}

/// Data operations for PULSE.
class PulseRepository {
  /// Creates the repository.
  PulseRepository(this._api);
  final ApiClient _api;

  /// Loads a single editorial batch of posts under [sort] (no infinite scroll —
  /// the redesign is a curated magazine, not a doom-feed).
  Future<List<Post>> fetch(PostSort sort, {int limit = 50}) async {
    final data = await _api.get(ApiEndpoints.posts, query: {
      'page': 1,
      'page_size': limit,
      'sort': sort.value,
    });
    return Paginated.fromJson(Map<String, dynamic>.from(data as Map), Post.fromJson).items;
  }

  /// Logs a like/dislike against a post.
  Future<void> react(String postId, {required bool like}) => _api.post(
        ApiEndpoints.interactions,
        body: {'content_id': postId, 'content_type': 'post', 'action': like ? 'like' : 'dislike'},
      );
}

/// PULSE data repository.
final pulseRepositoryProvider = Provider<PulseRepository>((ref) => PulseRepository(ref.watch(apiClientProvider)));

/// The loaded editorial batch for the current sort. Tone/creator filtering is
/// applied in the screen (client-side) so chip taps don't refetch.
class PulseFeedController extends AsyncNotifier<List<Post>> {
  @override
  Future<List<Post>> build() {
    final sort = ref.watch(pulseFilterProvider.select((f) => f.sort));
    return ref.read(pulseRepositoryProvider).fetch(sort);
  }

  /// Pull-to-refresh.
  Future<void> refresh() async {
    state = const AsyncLoading();
    final sort = ref.read(pulseFilterProvider).sort;
    state = await AsyncValue.guard(() => ref.read(pulseRepositoryProvider).fetch(sort));
  }
}

/// PULSE feed provider.
final pulseFeedProvider = AsyncNotifierProvider<PulseFeedController, List<Post>>(PulseFeedController.new);

/// Shared creator personas (for the filter sheet's creator group).
class CreatorsController extends AsyncNotifier<List<Creator>> {
  @override
  Future<List<Creator>> build() async {
    final data = await ref.read(apiClientProvider).get(ApiEndpoints.creators);
    final list = data is List ? data : (data is Map ? data['items'] as List? : null) ?? const [];
    return list.whereType<Map>().map((e) => Creator.fromJson(Map<String, dynamic>.from(e))).toList();
  }
}

/// Creators provider.
final creatorsProvider = AsyncNotifierProvider<CreatorsController, List<Creator>>(CreatorsController.new);
