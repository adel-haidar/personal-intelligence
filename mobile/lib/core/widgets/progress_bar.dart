import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';

/// A labelled amber progress bar used for brain health and the impact panel.
class AppProgressBar extends StatelessWidget {
  /// Creates a progress bar.
  const AppProgressBar({
    super.key,
    required this.value,
    this.label,
    this.hint,
    this.color,
  });

  /// 0–1 fill fraction.
  final double value;

  /// Optional leading label.
  final String? label;

  /// Optional hint shown under the bar (e.g. "Upload a statement to improve").
  final String? hint;

  /// Override the fill colour (defaults to brain amber).
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (label != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(label!, style: AppText.sm.copyWith(color: c.textSecondary)),
                Text('${(value * 100).round()}%',
                    style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
              ],
            ),
          ),
        ClipRRect(
          borderRadius: BorderRadius.circular(999),
          child: LinearProgressIndicator(
            value: value.clamp(0.0, 1.0),
            minHeight: 6,
            backgroundColor: c.backgroundRaised,
            valueColor: AlwaysStoppedAnimation(color ?? c.brainAmber),
          ),
        ),
        if (hint != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(hint!, style: AppText.xs.copyWith(color: c.textTertiary)),
          ),
      ],
    );
  }
}
