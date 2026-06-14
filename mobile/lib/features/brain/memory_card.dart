import 'package:flutter/material.dart';

import '../../core/models/memory.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/format.dart';
import '../../core/widgets/app_card.dart';

/// A single memory row in the Brain list. Tap to expand; swipe handled by the
/// parent [Dismissible].
class MemoryCard extends StatelessWidget {
  /// Creates a card for [memory].
  const MemoryCard({super.key, required this.memory, this.onTap});

  final Memory memory;
  final VoidCallback? onTap;

  IconData get _sourceIcon => switch (memory.source) {
        MemorySource.manual => Icons.edit_outlined,
        MemorySource.file => Icons.attach_file,
        MemorySource.device => Icons.watch_outlined,
        MemorySource.ai => Icons.smart_toy_outlined,
      };

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final preview = memory.content.length > 200 ? '${memory.content.substring(0, 200)}…' : memory.content;
    return AppCard(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(_sourceIcon, size: 16, color: c.textTertiary),
              const SizedBox(width: AppDimens.space2),
              Expanded(
                child: Text(memory.title,
                    maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: AppText.md.copyWith(color: c.textPrimary)),
              ),
              Text(Format.shortTime(memory.createdAt),
                  style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
            ],
          ),
          const SizedBox(height: AppDimens.space2),
          Text(
            preview,
            style: AppText.serif(size: 15, italic: memory.italicBody).copyWith(color: c.textSecondary),
          ),
          if (memory.tags.isNotEmpty) ...[
            const SizedBox(height: AppDimens.space3),
            Wrap(
              spacing: AppDimens.space2,
              runSpacing: AppDimens.space2,
              children: [
                for (final tag in memory.tags.take(4))
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: AppDimens.space2, vertical: 2),
                    decoration: BoxDecoration(
                      color: c.brainAmberSurface,
                      borderRadius: BorderRadius.circular(AppDimens.pillRadius),
                    ),
                    child: Text(tag, style: AppText.mono(size: 10).copyWith(color: c.brainAmber)),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
