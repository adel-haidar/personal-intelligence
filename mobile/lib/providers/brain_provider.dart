import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_client.dart';
import '../core/api/api_endpoints.dart';
import '../core/models/json_utils.dart';
import '../core/models/memory.dart';
import '../core/models/paginated.dart';
import 'core_providers.dart';

/// Brain size + freshness from `/memory/stats`.
class BrainStats {
  /// Constructs stats.
  const BrainStats({required this.total, this.lastUpdated});

  /// Total memory count.
  final int total;

  /// When the brain was last updated.
  final DateTime? lastUpdated;

  /// Decodes the stats payload.
  factory BrainStats.fromJson(Map<String, dynamic> json) => BrainStats(
        total: asInt(json['total']) ?? 0,
        lastUpdated: asDate(json['last_updated']),
      );

  /// A rough 0–1 "brain health" score that climbs with memory count.
  double get health => (total / 50).clamp(0.0, 1.0);
}

/// Loads and refreshes [BrainStats].
class BrainStatsController extends AsyncNotifier<BrainStats> {
  @override
  Future<BrainStats> build() => _load();

  Future<BrainStats> _load() async {
    final data = await ref.read(apiClientProvider).get(ApiEndpoints.memoryStats);
    return BrainStats.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// Re-fetches the stats.
  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(_load);
  }
}

/// Brain stats provider (powers the dashboard + brain header + impact panel).
final brainStatsProvider =
    AsyncNotifierProvider<BrainStatsController, BrainStats>(BrainStatsController.new);

/// Data operations for the Brain screen: paged list, search, add, delete.
class BrainRepository {
  /// Creates the repository over [_api].
  BrainRepository(this._api);
  final ApiClient _api;

  /// Fetches one page of memories (newest first).
  Future<Paginated<Memory>> page({required int page, int pageSize = 20, String? query}) async {
    final data = await _api.get(ApiEndpoints.memory, query: {
      'page': page,
      'page_size': pageSize,
      if (query != null && query.isNotEmpty) 'q': query,
    });
    return Paginated.fromJson(Map<String, dynamic>.from(data as Map), Memory.fromJson);
  }

  /// Semantic search over memory content.
  Future<List<Memory>> search(String query, {int k = 20}) async {
    final data = await _api.get(ApiEndpoints.memorySearch, query: {'q': query, 'k': k});
    final items = (data is Map ? data['items'] as List? : null) ?? const [];
    return items.whereType<Map>().map((e) => Memory.fromJson(Map<String, dynamic>.from(e))).toList();
  }

  /// Saves a free-text memory. Title defaults to the first line.
  Future<void> addText(String content, {String? title}) async {
    final trimmed = content.trim();
    final derivedTitle = (title ?? trimmed.split('\n').first).trim();
    await _api.post(ApiEndpoints.memoryText, body: {
      'title': derivedTitle.isEmpty ? 'Note' : derivedTitle,
      'content': trimmed,
    });
  }

  /// Uploads a document to be indexed into the brain.
  Future<void> uploadFile(String path, String filename) async {
    await _api.uploadFiles(
      ApiEndpoints.fileUpload,
      fileField: 'file',
      files: [await MultipartFile.fromFile(path, filename: filename)],
    );
  }

  /// Edits a memory's content/title.
  Future<void> update(String id, {String? title, String? content}) => _api.patch(
        ApiEndpoints.memoryById(id),
        body: {if (title != null) 'title': title, if (content != null) 'content': content},
      );

  /// Deletes a memory by id.
  Future<void> delete(String id) => _api.delete(ApiEndpoints.memoryById(id));
}

/// Brain data repository.
final brainRepositoryProvider = Provider<BrainRepository>(
  (ref) => BrainRepository(ref.watch(apiClientProvider)),
);

/// Live status of a brain-organiser run (`/brain/organise/status`).
class OrganiseStatus {
  /// Constructs status.
  const OrganiseStatus({required this.running, this.lastRunAt, this.message});

  /// Whether an organise run is currently in progress.
  final bool running;

  /// When the last run finished.
  final DateTime? lastRunAt;

  /// Optional human status message.
  final String? message;

  /// Decodes the status payload (tolerant of field naming).
  factory OrganiseStatus.fromJson(Map<String, dynamic> json) => OrganiseStatus(
        running: asBool(json['running']) || asStr(json['status']) == 'running',
        lastRunAt: asDate(json['last_run_at'] ?? json['finished_at'] ?? json['completed_at']),
        message: asStrOrNull(json['message']),
      );
}

/// Brain-organiser control: start a run + poll status.
class OrganiseController extends AsyncNotifier<OrganiseStatus> {
  @override
  Future<OrganiseStatus> build() => _status();

  Future<OrganiseStatus> _status() async {
    final data = await ref.read(apiClientProvider).get(ApiEndpoints.brainOrganiseStatus);
    return OrganiseStatus.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// Starts a run, then refreshes status. Safe if one is already running (409).
  Future<void> start() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      await ref.read(apiClientProvider).post(ApiEndpoints.brainOrganise);
      return _status();
    });
  }

  /// Polls the current status.
  Future<void> poll() async => state = await AsyncValue.guard(_status);
}

/// Brain organiser status/control.
final organiseProvider =
    AsyncNotifierProvider<OrganiseController, OrganiseStatus>(OrganiseController.new);
