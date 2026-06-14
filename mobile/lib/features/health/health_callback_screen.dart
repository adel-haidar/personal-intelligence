import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/brain_pulse.dart';

/// Landing screen for the wearable OAuth deep link
/// (`adel-intelligence://health/callback`).
///
/// When cloud-device connection lands on the backend, this screen would POST
/// the returned `code`/`state` to complete the link. For now it confirms the
/// redirect was received and routes back to Health.
class HealthCallbackScreen extends StatelessWidget {
  /// Creates the callback screen with the deep-link [query] parameters.
  const HealthCallbackScreen({super.key, required this.query});

  /// Query parameters from the OAuth redirect (`code`, `state`, `error`, …).
  final Map<String, String> query;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final error = query['error'];
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppDimens.space6),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const BrainPulse(size: 48),
                const SizedBox(height: AppDimens.space5),
                Text(
                  error != null ? 'Connection didn\'t complete' : 'Device connected',
                  style: AppText.lg.copyWith(color: c.textPrimary),
                ),
                const SizedBox(height: AppDimens.space2),
                Text(
                  error != null
                      ? 'You can try connecting again from the Health screen.'
                      : 'Your device will start syncing shortly.',
                  textAlign: TextAlign.center,
                  style: AppText.sm.copyWith(color: c.textSecondary),
                ),
                const SizedBox(height: AppDimens.space6),
                AppButton(label: 'Back to Health', onPressed: () => context.go(Routes.health)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
