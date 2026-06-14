import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_endpoints.dart';
import '../../core/models/memory.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/format.dart';
import '../../core/widgets/states.dart';
import '../../providers/core_providers.dart';

/// Deep-linkable full memory view (`/brain/memory/:id`).
///
/// The in-app expansion uses a bottom sheet; this route exists for deep links
/// and fetches the memory by id from `/memory/:id`.
class MemoryDetailScreen extends ConsumerWidget {
  /// Creates the detail screen for [memoryId].
  const MemoryDetailScreen({super.key, required this.memoryId});

  final String memoryId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final future = ref.watch(_memoryProvider(memoryId));
    return Scaffold(
      appBar: AppBar(title: const Text('Memory')),
      body: future.when(
        loading: () => const ShimmerList(count: 1),
        error: (_, __) => ErrorRetry(
          message: 'Couldn\'t load this memory.',
          onRetry: () => ref.invalidate(_memoryProvider(memoryId)),
        ),
        data: (m) => ListView(
          padding: const EdgeInsets.all(AppDimens.space5),
          children: [
            Text(m.title, style: AppText.lg.copyWith(color: c.textPrimary)),
            const SizedBox(height: AppDimens.space2),
            Text(Format.shortTime(m.createdAt), style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
            const SizedBox(height: AppDimens.space4),
            Text(m.content, style: AppText.serif(italic: m.italicBody).copyWith(color: c.textSecondary)),
          ],
        ),
      ),
    );
  }
}

final _memoryProvider = FutureProvider.family<Memory, String>((ref, id) async {
  final data = await ref.read(apiClientProvider).get(ApiEndpoints.memoryById(id));
  return Memory.fromJson(Map<String, dynamic>.from(data as Map));
});
