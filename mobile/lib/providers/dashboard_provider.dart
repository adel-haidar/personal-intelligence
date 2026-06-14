import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_endpoints.dart';
import '../core/models/json_utils.dart';
import '../core/models/memory.dart';
import '../core/models/paginated.dart';
import 'core_providers.dart';

/// Aggregated, read-only snapshot powering the Dashboard.
class DashboardData {
  /// Constructs the snapshot.
  const DashboardData({
    required this.memoryCount,
    required this.postCount,
    required this.videoCount,
    required this.recent,
    this.lastUpdated,
  });

  final int memoryCount;
  final int postCount;
  final int videoCount;

  /// A few newest memories, shown as recent activity.
  final List<Memory> recent;
  final DateTime? lastUpdated;

  /// 0–1 brain-health bar value.
  double get brainHealth => (memoryCount / 50).clamp(0.0, 1.0);
}

/// Loads everything the dashboard needs in parallel.
class DashboardController extends AsyncNotifier<DashboardData> {
  @override
  Future<DashboardData> build() => _load();

  Future<DashboardData> _load() async {
    final api = ref.read(apiClientProvider);
    final results = await Future.wait([
      api.get(ApiEndpoints.memoryStats),
      api.get(ApiEndpoints.posts, query: {'page': 1, 'page_size': 1}),
      api.get(ApiEndpoints.videos, query: {'page': 1, 'page_size': 1}),
      api.get(ApiEndpoints.memory, query: {'page': 1, 'page_size': 5}),
    ]);
    final stats = Map<String, dynamic>.from(results[0] as Map);
    final posts = Map<String, dynamic>.from(results[1] as Map);
    final videos = Map<String, dynamic>.from(results[2] as Map);
    final recentPage = Paginated.fromJson(Map<String, dynamic>.from(results[3] as Map), Memory.fromJson);
    return DashboardData(
      memoryCount: asInt(stats['total']) ?? 0,
      lastUpdated: asDate(stats['last_updated']),
      postCount: asInt(posts['total']) ?? 0,
      videoCount: asInt(videos['total']) ?? 0,
      recent: recentPage.items,
    );
  }

  /// Pull-to-refresh.
  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(_load);
  }
}

/// Dashboard aggregate provider.
final dashboardProvider = AsyncNotifierProvider<DashboardController, DashboardData>(DashboardController.new);
