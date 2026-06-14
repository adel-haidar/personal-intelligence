import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';

/// A horizontal-scroll filter pill (tone for PULSE, category for SIGNAL).
///
/// Inactive: surface fill + subtle border + secondary text. Active: filled with
/// [color] and white text — except amber, which uses the amber surface with
/// amber text rather than a filled amber pill.
class FeedChip extends StatelessWidget {
  /// Creates a chip.
  const FeedChip({
    super.key,
    required this.label,
    required this.active,
    required this.onTap,
    this.color,
  });

  final String label;
  final bool active;
  final VoidCallback onTap;

  /// The semantic colour used when active (defaults to the accent).
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final accent = color ?? c.accentPrimary;
    final isAmber = accent == c.brainAmber;

    final Color bg;
    final Color fg;
    final Color border;
    if (active) {
      bg = isAmber ? c.brainAmberSurface : accent;
      fg = isAmber ? c.brainAmber : Colors.white;
      border = accent;
    } else {
      bg = c.backgroundSurface;
      fg = c.textSecondary;
      border = c.borderSubtle;
    }

    return GestureDetector(
      onTap: onTap,
      child: Container(
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: border),
        ),
        child: Text(label, style: AppText.display(13).copyWith(color: fg, fontWeight: FontWeight.w500)),
      ),
    );
  }
}

/// A horizontal scrolling row of [FeedChip]s with the standard 16px gutters.
class FeedChipRow extends StatelessWidget {
  /// Creates a chip row from prebuilt [chips].
  const FeedChipRow({super.key, required this.chips});

  final List<Widget> chips;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(16, 2, 16, 14),
      child: Row(
        children: [
          for (var i = 0; i < chips.length; i++) ...[
            if (i > 0) const SizedBox(width: 8),
            chips[i],
          ],
        ],
      ),
    );
  }
}
