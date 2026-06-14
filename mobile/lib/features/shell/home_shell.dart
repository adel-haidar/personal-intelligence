import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/brain_pulse.dart';
import '../../providers/brain_provider.dart';
import '../../providers/feed_seen_provider.dart';
import '../aria/mini_player.dart';

/// The persistent bottom-nav shell hosting the four primary tabs and the
/// "More" sheet (Signal / Finances / Settings).
///
/// Restyled per the mobile handoff: 56px high, surface background, a 0.5px top
/// hairline, no elevation/indicator, icons-only with the label shown on the
/// active tab only. The Brain tab icon is the [BrainPulse]; with zero memories
/// it pulses slowly and its label reads "Start here" in amber.
class HomeShell extends ConsumerWidget {
  /// Wraps the active tab [child].
  const HomeShell({super.key, required this.child});

  final Widget child;

  static const _tabs = [Routes.dashboard, Routes.brain, Routes.pulse, Routes.health];

  int _currentIndex(BuildContext context) {
    final loc = GoRouterState.of(context).matchedLocation;
    final i = _tabs.indexWhere((t) => loc.startsWith(t));
    return i < 0 ? 0 : i;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final index = _currentIndex(context);
    final memoryCount = ref.watch(brainStatsProvider).valueOrNull?.total ?? 0;
    final emptyBrain = memoryCount == 0;
    final seen = ref.watch(feedSeenProvider);

    return Scaffold(
      body: child,
      bottomNavigationBar: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const MiniPlayer(),
          DecoratedBox(
        decoration: BoxDecoration(
          color: c.backgroundSurface,
          border: Border(top: BorderSide(color: c.isDark ? c.borderMedium : c.borderSubtle, width: 0.5)),
        ),
        child: NavigationBarTheme(
          data: NavigationBarThemeData(
            labelTextStyle: WidgetStatePropertyAll(
              AppText.xs.copyWith(fontWeight: FontWeight.w500, color: c.accentPrimary),
            ),
            iconTheme: WidgetStateProperty.resolveWith(
              (s) => IconThemeData(
                size: 22,
                color: s.contains(WidgetState.selected) ? c.accentPrimary : c.textTertiary,
              ),
            ),
          ),
          child: NavigationBar(
            selectedIndex: index,
            height: 56,
            backgroundColor: c.backgroundSurface,
            elevation: 0,
            indicatorColor: Colors.transparent,
            labelBehavior: NavigationDestinationLabelBehavior.onlyShowSelected,
            overlayColor: const WidgetStatePropertyAll(Colors.transparent),
            onDestinationSelected: (i) {
              if (i == 4) {
                _openMore(context);
              } else {
                context.go(_tabs[i]);
              }
            },
            destinations: [
              const NavigationDestination(icon: Icon(Icons.dashboard_outlined), selectedIcon: Icon(Icons.dashboard), label: 'Dashboard'),
              NavigationDestination(
                icon: BrainPulse(size: 16, slow: emptyBrain),
                label: emptyBrain ? 'Start here' : 'Brain',
              ),
              NavigationDestination(
                icon: _PresenceDot(show: !seen.pulse, child: const Icon(Icons.play_circle_outline)),
                selectedIcon: const Icon(Icons.play_circle),
                label: 'Pulse',
              ),
              const NavigationDestination(icon: Icon(Icons.favorite_border), selectedIcon: Icon(Icons.favorite), label: 'Health'),
              NavigationDestination(
                icon: _PresenceDot(show: !seen.signal || !seen.stories, child: const Icon(Icons.more_horiz)),
                label: 'More',
              ),
            ],
          ),
        ),
          ),
        ],
      ),
    );
  }

  void _openMore(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        final c = sheetContext.c;
        Widget tile(IconData icon, String title, String subtitle, String route) => ListTile(
              leading: Icon(icon, color: c.accentPrimary),
              title: Text(title, style: AppText.md.copyWith(color: c.textPrimary)),
              subtitle: Text(subtitle, style: AppText.sm.copyWith(color: c.textSecondary)),
              trailing: Icon(Icons.chevron_right, color: c.textTertiary),
              onTap: () {
                Navigator.of(sheetContext).pop();
                context.push(route);
              },
            );
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.only(bottom: AppDimens.space4),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                tile(Icons.video_library_outlined, 'Signal', 'Your AI video channel', Routes.signal),
                tile(Icons.movie_outlined, 'Stories', 'AI films and series', Routes.stories),
                tile(Icons.music_note_outlined, 'Aria', 'Music from your memories', Routes.aria),
                tile(Icons.account_balance_outlined, 'Finances', 'Your money, in plain language', Routes.finances),
                tile(Icons.settings_outlined, 'Settings', 'Profile, privacy and data', Routes.settings),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Overlays a 5px amber presence dot on the top-right of [child] when [show].
/// A presence indicator (new content exists), not a count badge.
class _PresenceDot extends StatelessWidget {
  const _PresenceDot({required this.child, required this.show});
  final Widget child;
  final bool show;

  @override
  Widget build(BuildContext context) {
    if (!show) return child;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        child,
        Positioned(
          top: -1,
          right: -3,
          child: Container(
            width: 5,
            height: 5,
            decoration: BoxDecoration(color: context.c.brainAmber, shape: BoxShape.circle),
          ),
        ),
      ],
    );
  }
}
