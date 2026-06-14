import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api/api_endpoints.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/format.dart';
import '../../core/widgets/toast.dart';
import '../../providers/auth_provider.dart';
import '../../providers/brain_provider.dart';
import '../../providers/core_providers.dart';
import '../../providers/theme_provider.dart';

/// Settings — profile, privacy & data, notifications (coming soon), and about.
class SettingsScreen extends ConsumerWidget {
  /// Creates the Settings screen.
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final auth = ref.watch(authControllerProvider);
    final user = auth is AuthSignedIn ? auth.user : null;
    final organise = ref.watch(organiseProvider);
    final themeMode = ref.watch(themeControllerProvider);

    return Scaffold(
      appBar: AppBar(title: Text('Settings', style: AppText.md.copyWith(color: c.textPrimary))),
      body: ListView(
        children: [
          _SectionHeader('Profile'),
          ListTile(
            leading: CircleAvatar(
              backgroundColor: c.accentSurface,
              child: Text(
                (user?.displayName.isNotEmpty ?? false) ? user!.displayName[0].toUpperCase() : '?',
                style: AppText.md.copyWith(color: c.accentPrimary),
              ),
            ),
            title: Text(user?.displayName ?? '—', style: AppText.md.copyWith(color: c.textPrimary)),
            subtitle: Text('Tap to edit', style: AppText.sm.copyWith(color: c.textSecondary)),
            onTap: () => _editName(context, ref, user?.displayName ?? ''),
          ),
          ListTile(
            title: Text('Email', style: AppText.base.copyWith(color: c.textPrimary)),
            subtitle: Text(user?.email ?? '—', style: AppText.sm.copyWith(color: c.textSecondary)),
          ),
          _SectionHeader('Appearance'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppDimens.space4, vertical: AppDimens.space2),
            child: Row(
              children: [
                Expanded(child: Text('Theme', style: AppText.base.copyWith(color: c.textPrimary))),
                SegmentedButton<ThemeMode>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: ThemeMode.light, icon: Icon(Icons.light_mode_outlined), tooltip: 'Light'),
                    ButtonSegment(value: ThemeMode.dark, icon: Icon(Icons.dark_mode_outlined), tooltip: 'Dark'),
                    ButtonSegment(value: ThemeMode.system, icon: Icon(Icons.smartphone_outlined), tooltip: 'System'),
                  ],
                  selected: {themeMode},
                  onSelectionChanged: (s) => ref.read(themeControllerProvider.notifier).set(s.first),
                ),
              ],
            ),
          ),

          _SectionHeader('Privacy & data'),
          ListTile(
            leading: Icon(Icons.download_outlined, color: c.textSecondary),
            title: Text('Export all my data', style: AppText.base.copyWith(color: c.textPrimary)),
            onTap: () => _export(context, ref),
          ),
          ListTile(
            leading: Icon(Icons.auto_awesome_outlined, color: c.textSecondary),
            title: Text('Organise brain memory', style: AppText.base.copyWith(color: c.textPrimary)),
            subtitle: Text(
              organise.valueOrNull?.running == true
                  ? 'Running…'
                  : organise.valueOrNull?.lastRunAt != null
                      ? 'Last run ${Format.relative(organise.valueOrNull!.lastRunAt)}'
                      : 'Reorganise and de-duplicate your memories',
              style: AppText.sm.copyWith(color: c.textSecondary),
            ),
            trailing: organise.valueOrNull?.running == true
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : null,
            enabled: organise.valueOrNull?.running != true,
            onTap: () async {
              await ref.read(organiseProvider.notifier).start();
              if (context.mounted) AppToast.show(context, 'Organising your brain…');
            },
          ),
          ListTile(
            leading: Icon(Icons.cleaning_services_outlined, color: c.brainAmber),
            title: Text('Clear my brain', style: AppText.base.copyWith(color: c.textPrimary)),
            onTap: () => _clearBrain(context, ref),
          ),
          ListTile(
            leading: Icon(Icons.delete_forever_outlined, color: c.danger),
            title: Text('Delete my account', style: AppText.base.copyWith(color: c.danger)),
            onTap: () => _deleteAccount(context, ref),
          ),

          _SectionHeader('Notifications'),
          SwitchListTile(
            title: Text('Push notifications', style: AppText.base.copyWith(color: c.textTertiary)),
            subtitle: Text('Coming soon', style: AppText.sm.copyWith(color: c.textTertiary)),
            value: false,
            onChanged: null,
          ),
          SwitchListTile(
            title: Text('Email digests', style: AppText.base.copyWith(color: c.textTertiary)),
            subtitle: Text('Coming soon', style: AppText.sm.copyWith(color: c.textTertiary)),
            value: false,
            onChanged: null,
          ),

          _SectionHeader('About'),
          const _VersionTile(),
          ListTile(
            leading: Icon(Icons.code, color: c.textSecondary),
            title: Text('GitHub', style: AppText.base.copyWith(color: c.textPrimary)),
            subtitle: Text('Self-hosted on your own server', style: AppText.sm.copyWith(color: c.textSecondary)),
            onTap: () => launchUrl(
              Uri.parse('https://github.com/'),
              mode: LaunchMode.externalApplication,
            ),
          ),
          const SizedBox(height: AppDimens.space5),
          Center(
            child: TextButton(
              onPressed: () async {
                await ref.read(authControllerProvider.notifier).logout();
                if (context.mounted) context.go(Routes.login);
              },
              child: Text('Sign out', style: AppText.base.copyWith(color: c.textSecondary)),
            ),
          ),
          const SizedBox(height: AppDimens.space8),
        ],
      ),
    );
  }

  Future<void> _editName(BuildContext context, WidgetRef ref, String current) async {
    final controller = TextEditingController(text: current);
    final newName = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Display name'),
        content: TextField(controller: controller, autofocus: true),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, controller.text.trim()), child: const Text('Save')),
        ],
      ),
    );
    if (newName == null || newName.isEmpty || newName == current) return;
    try {
      await ref.read(apiClientProvider).patch(ApiEndpoints.profile, body: {'display_name': newName});
      await ref.read(authControllerProvider.notifier).refreshUser();
      if (context.mounted) AppToast.show(context, '✓ Saved');
    } catch (e) {
      if (context.mounted) AppToast.show(context, '$e', isError: true);
    }
  }

  Future<void> _export(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(apiClientProvider).get(ApiEndpoints.exportData);
      if (context.mounted) AppToast.show(context, 'Your data export has started.');
    } catch (e) {
      if (context.mounted) AppToast.show(context, '$e', isError: true);
    }
  }

  Future<void> _clearBrain(BuildContext context, WidgetRef ref) async {
    final c = context.c;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Clear my brain?'),
        content: Text('This permanently deletes every memory. Your account stays.',
            style: AppText.sm.copyWith(color: c.textSecondary)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: Text('Clear', style: TextStyle(color: c.brainAmber))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(apiClientProvider).post(ApiEndpoints.clearBrain);
      ref.read(brainStatsProvider.notifier).refresh();
      if (context.mounted) AppToast.show(context, 'Your brain has been cleared.');
    } catch (e) {
      if (context.mounted) AppToast.show(context, '$e', isError: true);
    }
  }

  Future<void> _deleteAccount(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => const _DeleteAccountDialog(),
    );
    if (confirmed != true) return;
    try {
      await ref.read(apiClientProvider).delete(ApiEndpoints.deleteAccount);
      await ref.read(authControllerProvider.notifier).logout();
      if (context.mounted) context.go(Routes.login);
    } catch (e) {
      if (context.mounted) AppToast.show(context, '$e', isError: true);
    }
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);
  final String title;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppDimens.space4, AppDimens.space5, AppDimens.space4, AppDimens.space2),
      child: Text(title.toUpperCase(),
          style: AppText.mono(size: 11, weight: FontWeight.w600).copyWith(color: c.textTertiary)),
    );
  }
}

class _VersionTile extends StatelessWidget {
  const _VersionTile();

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return FutureBuilder<PackageInfo>(
      future: PackageInfo.fromPlatform(),
      builder: (_, snap) => ListTile(
        leading: Icon(Icons.info_outline, color: c.textSecondary),
        title: Text('Version', style: AppText.base.copyWith(color: c.textPrimary)),
        subtitle: Text(
          snap.hasData ? '${snap.data!.version} (${snap.data!.buildNumber})' : '—',
          style: AppText.mono(size: 12).copyWith(color: c.textSecondary),
        ),
      ),
    );
  }
}

class _DeleteAccountDialog extends StatefulWidget {
  const _DeleteAccountDialog();
  @override
  State<_DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends State<_DeleteAccountDialog> {
  final _controller = TextEditingController();
  bool _enabled = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AlertDialog(
      title: const Text('Delete my account'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('This permanently deletes your account and all your data. Type DELETE to confirm.',
              style: AppText.sm.copyWith(color: c.textSecondary)),
          const SizedBox(height: AppDimens.space3),
          TextField(
            controller: _controller,
            autofocus: true,
            decoration: const InputDecoration(hintText: 'DELETE'),
            onChanged: (v) => setState(() => _enabled = v.trim() == 'DELETE'),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        TextButton(
          onPressed: _enabled ? () => Navigator.pop(context, true) : null,
          child: Text('Delete', style: TextStyle(color: _enabled ? c.danger : c.textTertiary)),
        ),
      ],
    );
  }
}
