import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_dimens.dart';
import '../theme/app_text_styles.dart';

/// A coloured pill describing a PULSE post's tone, matching the web palette.
class TonePill extends StatelessWidget {
  /// Creates a pill for the given [tone] string.
  const TonePill({super.key, required this.tone});

  /// Raw tone value from the post (e.g. "analytical", "optimistic").
  final String tone;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final (fg, bg) = _colors(c, tone.toLowerCase());
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppDimens.space3, vertical: 3),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(AppDimens.pillRadius),
      ),
      child: Text(_pretty(tone), style: AppText.xs.copyWith(color: fg, fontWeight: FontWeight.w600)),
    );
  }

  String _pretty(String t) => t.isEmpty ? 'Neutral' : '${t[0].toUpperCase()}${t.substring(1)}';

  // Four canonical variants from the handoff:
  // Critical = danger bg · Satirical = amber surface · Supportive = success bg ·
  // Informative = accent surface.
  (Color, Color) _colors(AppPalette c, String t) {
    switch (t) {
      case 'critical':
      case 'cautionary':
      case 'urgent':
      case 'alarming':
        return (c.danger, c.dangerSurface);
      case 'supportive':
      case 'optimistic':
      case 'hopeful':
      case 'positive':
        return (c.success, c.successSurface);
      case 'satirical':
      case 'sarcastic':
      case 'ironic':
        return (c.brainAmber, c.brainAmberSurface);
      case 'informative':
      case 'analytical':
      case 'neutral':
      default:
        return (c.accentPrimary, c.accentSurface);
    }
  }
}
