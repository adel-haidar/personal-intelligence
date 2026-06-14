import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';

/// Returns the editorial score colour: green > 65 · amber 40–65 · red < 40.
Color scoreColor(BuildContext context, int score) => switch (score) {
      > 65 => context.c.success,
      >= 40 => context.c.brainAmber,
      _ => context.c.danger,
    };

/// Colored, background-less mono score text rendered as a 2-decimal value
/// (e.g. "0.81"). Pass [onDark] to force white on a hero scrim.
class ScoreText extends StatelessWidget {
  /// Creates a score text from a 0–1 [score].
  const ScoreText({super.key, required this.score, this.onDark = false, this.size = 11});

  final double score;
  final bool onDark;
  final double size;

  @override
  Widget build(BuildContext context) {
    final color = onDark ? Colors.white : scoreColor(context, (score * 100).round());
    return Text(
      score.toStringAsFixed(2),
      style: AppText.mono(size: size, weight: FontWeight.w500).copyWith(color: color),
    );
  }
}

/// A small JetBrains Mono badge showing a 0–100 score, coloured by band.
class ScoreBadge extends StatelessWidget {
  /// Creates a badge for [score] (0–100).
  const ScoreBadge({super.key, required this.score});

  final int score;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    // Handoff thresholds: green > 65 · amber 40–65 · red < 40.
    final color = switch (score) {
      > 65 => c.success,
      >= 40 => c.brainAmber,
      _ => c.danger,
    };
    return Text(
      score.toString().padLeft(2, '0'),
      style: AppText.mono(size: 11, weight: FontWeight.w600).copyWith(color: color),
    );
  }
}
