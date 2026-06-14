import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';

/// A like / dislike / open action button. On tap it fills with [color] for
/// 300ms (then settles, unless [active]) — the calm feedback gesture used
/// across PULSE and the SIGNAL player.
class VoteButton extends StatefulWidget {
  /// Creates a vote button.
  const VoteButton({
    super.key,
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
    this.active = false,
  });

  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  /// Whether this option is the persisted selection (stays filled).
  final bool active;

  @override
  State<VoteButton> createState() => _VoteButtonState();
}

class _VoteButtonState extends State<VoteButton> {
  bool _flash = false;

  void _handle() {
    setState(() => _flash = true);
    widget.onTap();
    Future.delayed(const Duration(milliseconds: 300), () {
      if (mounted) setState(() => _flash = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final on = widget.active || _flash;
    return GestureDetector(
      onTap: _handle,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        height: 36,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          color: on ? widget.color : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: on ? widget.color : c.borderSubtle),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(widget.icon, size: 16, color: on ? Colors.white : c.textSecondary),
            const SizedBox(width: 5),
            Text(widget.label,
                style: AppText.sm.copyWith(color: on ? Colors.white : c.textSecondary)),
          ],
        ),
      ),
    );
  }
}
