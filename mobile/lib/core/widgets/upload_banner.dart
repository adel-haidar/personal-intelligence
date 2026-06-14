import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_dimens.dart';
import '../theme/app_text_styles.dart';
import 'app_button.dart';
import 'app_card.dart';

/// A left-accent banner prompting the user to upload data or connect a device.
///
/// Used by Health (amber accent) and Finances (info/blue accent).
class UploadBanner extends StatelessWidget {
  /// Creates an upload banner.
  const UploadBanner({
    super.key,
    required this.title,
    required this.body,
    required this.accent,
    this.primaryLabel,
    this.onPrimary,
    this.secondaryLabel,
    this.onSecondary,
    this.privacyNote,
    this.onDismiss,
  });

  final String title;
  final String body;
  final Color accent;
  final String? primaryLabel;
  final VoidCallback? onPrimary;
  final String? secondaryLabel;
  final VoidCallback? onSecondary;
  final String? privacyNote;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AppCard(
      accentBorderColor: accent,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(title, style: AppText.md.copyWith(color: c.textPrimary))),
              if (onDismiss != null)
                IconButton(
                  icon: Icon(Icons.close, size: 18, color: c.textTertiary),
                  onPressed: onDismiss,
                  visualDensity: VisualDensity.compact,
                ),
            ],
          ),
          const SizedBox(height: AppDimens.space2),
          Text(body, style: AppText.sm.copyWith(color: c.textSecondary)),
          const SizedBox(height: AppDimens.space4),
          Wrap(
            spacing: AppDimens.space3,
            runSpacing: AppDimens.space2,
            children: [
              if (primaryLabel != null)
                AppButton(label: primaryLabel!, onPressed: onPrimary, icon: Icons.upload_file),
              if (secondaryLabel != null)
                AppButton(
                  label: secondaryLabel!,
                  onPressed: onSecondary,
                  variant: AppButtonVariant.outlined,
                  icon: Icons.add_link,
                ),
            ],
          ),
          if (privacyNote != null) ...[
            const SizedBox(height: AppDimens.space3),
            Text(privacyNote!, style: AppText.xs.copyWith(color: c.textTertiary)),
          ],
        ],
      ),
    );
  }
}
