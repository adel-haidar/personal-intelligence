import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_dimens.dart';
import '../theme/app_text_styles.dart';
import 'app_button.dart';
import 'app_card.dart';

/// A wearable-provider tile with a connect/connected action.
///
/// Cloud providers (Garmin/WHOOP/Oura) connect via OAuth; native providers
/// (Apple Health / Health Connect) connect via the Open Wearables SDK. When
/// [comingSoon] is true the button is disabled — the backend has no device
/// connection endpoint yet.
class DeviceConnectionCard extends StatelessWidget {
  /// Creates a device card.
  const DeviceConnectionCard({
    super.key,
    required this.name,
    required this.icon,
    this.connected = false,
    this.comingSoon = false,
    this.onConnect,
    this.onDisconnect,
    this.busy = false,
  });

  final String name;
  final IconData icon;
  final bool connected;
  final bool comingSoon;
  final VoidCallback? onConnect;
  final VoidCallback? onDisconnect;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: connected ? c.success : c.textSecondary, size: 22),
              const SizedBox(width: AppDimens.space2),
              Expanded(
                child: Text(name, style: AppText.md.copyWith(color: c.textPrimary), overflow: TextOverflow.ellipsis),
              ),
            ],
          ),
          const SizedBox(height: AppDimens.space3),
          if (comingSoon)
            Text('Coming soon', style: AppText.xs.copyWith(color: c.textTertiary))
          else if (connected)
            AppButton(
              label: 'Disconnect',
              variant: AppButtonVariant.ghost,
              danger: true,
              onPressed: onDisconnect,
              loading: busy,
            )
          else
            AppButton(
              label: 'Connect',
              variant: AppButtonVariant.outlined,
              onPressed: onConnect,
              loading: busy,
            ),
        ],
      ),
    );
  }
}
