import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/format.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/brain_pulse.dart';
import '../../core/widgets/progress_bar.dart';
import '../../core/widgets/states.dart';
import '../../providers/auth_provider.dart';
import '../../providers/dashboard_provider.dart';

/// The home dashboard: greeting, brain card, module cards, recent activity.
class DashboardScreen extends ConsumerWidget {
  /// Creates the dashboard.
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final auth = ref.watch(authControllerProvider);
    final name = (auth is AuthSignedIn ? auth.user?.firstName : null) ?? 'there';
    final data = ref.watch(dashboardProvider);

    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          color: c.brainAmber,
          onRefresh: () => ref.read(dashboardProvider.notifier).refresh(),
          child: data.when(
            loading: () => const ShimmerList(),
            error: (e, _) => ListView(children: [
              const SizedBox(height: 120),
              ErrorRetry(
                message: e is ApiException ? e.message : 'Couldn\'t load your dashboard.',
                onRetry: () => ref.read(dashboardProvider.notifier).refresh(),
              ),
            ]),
            data: (d) => ListView(
              padding: const EdgeInsets.all(AppDimens.space4),
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text('${Format.greeting()}, $name.', style: AppText.lg.copyWith(color: c.textPrimary)),
                    ),
                    Text(Format.shortTime(DateTime.now()),
                        style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                  ],
                ),
                const SizedBox(height: AppDimens.space5),
                _BrainCard(memoryCount: d.memoryCount, health: d.brainHealth, lastUpdated: d.lastUpdated),
                const SizedBox(height: AppDimens.space4),
                _ModuleRow(postCount: d.postCount, videoCount: d.videoCount),
                const SizedBox(height: AppDimens.space6),
                Text('Recent activity', style: AppText.md.copyWith(color: c.textPrimary)),
                const SizedBox(height: AppDimens.space2),
                if (d.recent.isEmpty)
                  Text('Nothing yet. Add to your brain to get started.',
                      style: AppText.sm.copyWith(color: c.textTertiary))
                else
                  for (final m in d.recent)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: AppDimens.space2),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.center,
                        children: [
                          Container(
                            width: 7,
                            height: 7,
                            decoration: BoxDecoration(color: c.brainAmber, shape: BoxShape.circle),
                          ),
                          const SizedBox(width: AppDimens.space3),
                          Expanded(
                            child: Text(m.title.isEmpty ? m.content : m.title,
                                maxLines: 1, overflow: TextOverflow.ellipsis,
                                style: AppText.sm.copyWith(color: c.textSecondary)),
                          ),
                          Text(Format.relative(m.createdAt),
                              style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                        ],
                      ),
                    ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _BrainCard extends StatelessWidget {
  const _BrainCard({required this.memoryCount, required this.health, required this.lastUpdated});
  final int memoryCount;
  final double health;
  final DateTime? lastUpdated;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AppCard(
      onTap: () => context.go(Routes.brain),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const BrainPulse(size: 32),
              const SizedBox(width: AppDimens.space3),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('$memoryCount memories',
                      style: AppText.md.copyWith(color: c.textPrimary)),
                  Text('Updated ${Format.relative(lastUpdated)}',
                      style: AppText.xs.copyWith(color: c.textTertiary)),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppDimens.space4),
          AppProgressBar(value: health, label: 'Brain health'),
          const SizedBox(height: AppDimens.space4),
          AppButton(
            label: '+ Add to your brain',
            variant: AppButtonVariant.outlined,
            onPressed: () => context.go('${Routes.brain}?focus=1'),
          ),
        ],
      ),
    );
  }
}

class _ModuleRow extends StatelessWidget {
  const _ModuleRow({required this.postCount, required this.videoCount});
  final int postCount;
  final int videoCount;

  @override
  Widget build(BuildContext context) {
    // Horizontal scroll of 160px cards; the next card peeks in from the edge.
    return SizedBox(
      height: 132,
      child: ListView(
        scrollDirection: Axis.horizontal,
        clipBehavior: Clip.none,
        children: [
          _ModuleCard(title: 'Pulse', stat: '$postCount posts in your feed', icon: Icons.play_circle_outline, onOpen: () => context.go(Routes.pulse)),
          const SizedBox(width: AppDimens.space3),
          _ModuleCard(title: 'Signal', stat: '$videoCount videos', icon: Icons.video_library_outlined, onOpen: () => context.push(Routes.signal)),
          const SizedBox(width: AppDimens.space3),
          _ModuleCard(title: 'Health', stat: 'Your body at a glance', icon: Icons.favorite_border, onOpen: () => context.go(Routes.health)),
        ],
      ),
    );
  }
}

class _ModuleCard extends StatelessWidget {
  const _ModuleCard({required this.title, required this.stat, required this.icon, required this.onOpen});
  final String title;
  final String stat;
  final IconData icon;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return SizedBox(
      width: 160,
      child: AppCard(
        onTap: onOpen,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Icon(icon, color: c.accentPrimary),
            Text(title, style: AppText.md.copyWith(color: c.textPrimary)),
            Expanded(
              child: Text(stat, style: AppText.sm.copyWith(color: c.textSecondary),
                  maxLines: 2, overflow: TextOverflow.ellipsis),
            ),
            Text('Open →', style: AppText.sm.copyWith(color: c.accentPrimary)),
          ],
        ),
      ),
    );
  }
}
