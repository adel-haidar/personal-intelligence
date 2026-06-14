import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';

/// A magazine masthead header — the spaced-out wordmark (e.g. `PULSE`) with a
/// single trailing icon action. Replaces the plain page-title AppBar on the
/// editorial screens. The 56px top inset is provided by the surrounding
/// SafeArea; this adds the masthead padding.
class Masthead extends StatelessWidget {
  /// Creates a masthead titled [title] with a trailing [actionIcon].
  const Masthead({super.key, required this.title, required this.actionIcon, required this.onAction});

  final String title;
  final IconData actionIcon;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 8, 10),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            title,
            style: AppText.display(15).copyWith(color: c.textPrimary, letterSpacing: 0.16 * 15),
          ),
          IconButton(
            icon: Icon(actionIcon, size: 20, color: c.textPrimary),
            onPressed: onAction,
          ),
        ],
      ),
    );
  }
}
