import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_dimens.dart';
import '../theme/app_text_styles.dart';

/// Button visual variants.
enum AppButtonVariant {
  /// Filled accent (indigo) primary action.
  primary,

  /// Bordered, transparent fill.
  outlined,

  /// Text-only ghost.
  ghost,
}

/// The app's button. Plus Jakarta Sans label, indigo accent, 8px radius.
///
/// Shows a small spinner and disables interaction while [loading].
class AppButton extends StatelessWidget {
  /// Creates a button.
  const AppButton({
    super.key,
    required this.label,
    this.onPressed,
    this.variant = AppButtonVariant.primary,
    this.icon,
    this.loading = false,
    this.expand = false,
    this.danger = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final AppButtonVariant variant;
  final IconData? icon;
  final bool loading;

  /// Stretch to the available width.
  final bool expand;

  /// Render in the danger colour (destructive actions).
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final accent = danger ? c.danger : c.accentPrimary;
    final disabled = onPressed == null || loading;

    final child = Row(
      mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (loading)
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: variant == AppButtonVariant.primary ? Colors.white : accent,
            ),
          )
        else if (icon != null) ...[
          Icon(icon, size: 18),
          const SizedBox(width: AppDimens.space2),
        ],
        if (!loading) Text(label, style: AppText.button),
      ],
    );

    final padding = const EdgeInsets.symmetric(
      horizontal: AppDimens.space5,
      vertical: AppDimens.space3,
    );
    final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppDimens.inputRadius));
    // Primary actions are 48 tall; secondary/ghost are the 36 compact height.
    final minSize = Size(0, variant == AppButtonVariant.primary ? 48 : 36);

    switch (variant) {
      case AppButtonVariant.primary:
        return FilledButton(
          onPressed: disabled ? null : onPressed,
          style: FilledButton.styleFrom(
            backgroundColor: accent,
            foregroundColor: Colors.white,
            disabledBackgroundColor: accent.withValues(alpha: 0.5),
            padding: padding,
            shape: shape,
            minimumSize: minSize,
          ),
          child: child,
        );
      case AppButtonVariant.outlined:
        return OutlinedButton(
          onPressed: disabled ? null : onPressed,
          style: OutlinedButton.styleFrom(
            foregroundColor: accent,
            side: BorderSide(color: disabled ? c.borderSubtle : accent),
            padding: padding,
            shape: shape,
            minimumSize: minSize,
          ),
          child: child,
        );
      case AppButtonVariant.ghost:
        return TextButton(
          onPressed: disabled ? null : onPressed,
          style: TextButton.styleFrom(
              foregroundColor: accent, padding: padding, shape: shape, minimumSize: minSize),
          child: child,
        );
    }
  }
}
