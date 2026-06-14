import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../theme/app_colors.dart';
import '../theme/app_dimens.dart';
import '../theme/app_text_styles.dart';
import 'app_button.dart';

/// A shimmering placeholder block for content-area loading states.
///
/// Use instead of a spinner for anything that will become real content.
class ShimmerBox extends StatelessWidget {
  /// Creates a shimmer block.
  const ShimmerBox({
    super.key,
    this.height = 16,
    this.width = double.infinity,
    this.radius = AppDimens.inputRadius,
  });

  final double height;
  final double width;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Shimmer.fromColors(
      baseColor: c.backgroundRaised,
      highlightColor: c.borderSubtle,
      child: Container(
        height: height,
        width: width,
        decoration: BoxDecoration(
          color: c.backgroundRaised,
          borderRadius: BorderRadius.circular(radius),
        ),
      ),
    );
  }
}

/// A stack of [ShimmerBox] card skeletons for list loading.
class ShimmerList extends StatelessWidget {
  /// Creates [count] skeleton cards.
  const ShimmerList({super.key, this.count = 5});
  final int count;

  @override
  Widget build(BuildContext context) {
    return ListView.separated(
      padding: const EdgeInsets.all(AppDimens.space4),
      itemCount: count,
      separatorBuilder: (_, __) => const SizedBox(height: AppDimens.space3),
      itemBuilder: (_, __) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: const [
          ShimmerBox(height: 14, width: 140),
          SizedBox(height: 10),
          ShimmerBox(height: 12),
          SizedBox(height: 6),
          ShimmerBox(height: 12, width: 220),
        ],
      ),
    );
  }
}

/// A centered error state with a retry button.
class ErrorRetry extends StatelessWidget {
  /// Creates an error state.
  const ErrorRetry({super.key, required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppDimens.space8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.cloud_off_outlined, size: 40, color: c.textTertiary),
            const SizedBox(height: AppDimens.space4),
            Text(message, textAlign: TextAlign.center, style: AppText.base.copyWith(color: c.textSecondary)),
            const SizedBox(height: AppDimens.space4),
            AppButton(label: 'Try again', variant: AppButtonVariant.ghost, onPressed: onRetry),
          ],
        ),
      ),
    );
  }
}

/// A centered empty state: calm Lora-serif text + an optional CTA.
class EmptyState extends StatelessWidget {
  /// Creates an empty state.
  const EmptyState({super.key, required this.message, this.ctaLabel, this.onCta, this.icon});
  final String message;
  final String? ctaLabel;
  final VoidCallback? onCta;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppDimens.space8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 36, color: c.textTertiary),
              const SizedBox(height: AppDimens.space4),
            ],
            Text(
              message,
              textAlign: TextAlign.center,
              style: AppText.serif(size: 18).copyWith(color: c.textSecondary),
            ),
            if (ctaLabel != null) ...[
              const SizedBox(height: AppDimens.space5),
              AppButton(label: ctaLabel!, onPressed: onCta),
            ],
          ],
        ),
      ),
    );
  }
}
