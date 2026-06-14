import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/feed_chip.dart';
import '../../providers/pulse_provider.dart';

/// Opens the PULSE filter bottom sheet (Sort / Tone / Creator chip groups).
/// Selections commit live to [pulseFilterProvider]; "Show results" dismisses.
void showPulseFilterSheet(BuildContext context, WidgetRef ref) {
  showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (_) => const _PulseFilterSheet(),
  );
}

class _PulseFilterSheet extends ConsumerWidget {
  const _PulseFilterSheet();

  static const _tones = ['all', 'informative', 'satirical', 'critical', 'supportive'];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final filter = ref.watch(pulseFilterProvider);
    final notifier = ref.read(pulseFilterProvider.notifier);
    final creators = ref.watch(creatorsProvider).valueOrNull ?? const [];

    Color toneColor(String t) => switch (t) {
          'critical' => c.danger,
          'satirical' => c.brainAmber,
          'supportive' => c.success,
          'informative' => c.accentPrimary,
          _ => c.accentPrimary,
        };

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(AppDimens.space4, 0, AppDimens.space4, AppDimens.space5),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Filter Pulse', style: AppText.md.copyWith(color: c.textPrimary)),
            const SizedBox(height: AppDimens.space4),
            _Group(
              label: 'Sort',
              children: [
                for (final s in PostSort.values)
                  FeedChip(label: s.label, active: filter.sort == s, onTap: () => notifier.setSort(s)),
              ],
            ),
            _Group(
              label: 'Tone',
              children: [
                for (final t in _tones)
                  FeedChip(
                    label: t == 'all' ? 'All' : '${t[0].toUpperCase()}${t.substring(1)}',
                    active: filter.tone == t,
                    color: toneColor(t),
                    onTap: () => notifier.setTone(t),
                  ),
              ],
            ),
            _Group(
              label: 'Creator',
              children: [
                FeedChip(label: 'All', active: filter.creatorId == null, onTap: () => notifier.setCreator(null)),
                for (final cr in creators)
                  FeedChip(
                    label: cr.name,
                    active: filter.creatorId == cr.slug,
                    onTap: () => notifier.setCreator(cr.slug),
                  ),
              ],
            ),
            const SizedBox(height: AppDimens.space2),
            AppButton(label: 'Show results', expand: true, onPressed: () => Navigator.of(context).pop()),
          ],
        ),
      ),
    );
  }
}

class _Group extends StatelessWidget {
  const _Group({required this.label, required this.children});
  final String label;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(),
              style: AppText.mono(size: 11, weight: FontWeight.w600).copyWith(color: c.textTertiary)),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: children),
        ],
      ),
    );
  }
}
