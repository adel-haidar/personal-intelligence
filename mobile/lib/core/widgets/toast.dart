import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';

/// Lightweight, action-less confirmation toasts (e.g. "✓ Feedback saved").
class AppToast {
  AppToast._();

  /// Shows a 2-second floating snackbar with [message].
  static void show(BuildContext context, String message, {bool isError = false}) {
    final c = context.c;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(
          duration: const Duration(seconds: 2),
          content: Text(
            message,
            style: AppText.sm.copyWith(color: isError ? c.danger : c.textPrimary),
          ),
          backgroundColor: c.backgroundRaised,
        ),
      );
  }
}
