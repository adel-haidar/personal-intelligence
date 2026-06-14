import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_dimens.dart';
import '../theme/app_text_styles.dart';
import 'app_card.dart';

/// A plain-language insight card for health/finance: a title, a Lora-serif body,
/// optional status chips, and an optional trailing action (e.g. "Show numbers").
class InsightCard extends StatelessWidget {
  /// Creates an insight card.
  const InsightCard({
    super.key,
    required this.title,
    required this.body,
    this.chips = const [],
    this.trailing,
    this.child,
  });

  final String title;
  final String body;

  /// Status chips ((label, color)) rendered under the title.
  final List<({String label, Color color})> chips;

  /// Optional action row at the bottom (e.g. a toggle button).
  final Widget? trailing;

  /// Optional extra widget (chart, numbers) below the body.
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: AppText.md.copyWith(color: c.textPrimary)),
          if (chips.isNotEmpty) ...[
            const SizedBox(height: AppDimens.space2),
            Wrap(
              spacing: AppDimens.space2,
              runSpacing: AppDimens.space2,
              children: [
                for (final chip in chips)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: AppDimens.space3, vertical: 3),
                    decoration: BoxDecoration(
                      color: chip.color.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(AppDimens.pillRadius),
                    ),
                    child: Text(chip.label,
                        style: AppText.xs.copyWith(color: chip.color, fontWeight: FontWeight.w600)),
                  ),
              ],
            ),
          ],
          const SizedBox(height: AppDimens.space3),
          Text(body, style: AppText.serif(size: 15).copyWith(color: c.textSecondary)),
          if (child != null) ...[const SizedBox(height: AppDimens.space4), child!],
          if (trailing != null) ...[const SizedBox(height: AppDimens.space2), trailing!],
        ],
      ),
    );
  }
}
