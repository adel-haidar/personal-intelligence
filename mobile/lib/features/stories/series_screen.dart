import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/story.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/brain_pulse.dart';
import '../../core/widgets/states.dart';
import '../../providers/stories_provider.dart';
import 'stories_widgets.dart';

/// Series page (box set) — hero banner, Play + Save toggle, episode list rows.
/// Backed by `GET /api/stories/series/{id}` (+ episodes).
///
/// The backend exposes no tagline, score, topics, or per-episode watch
/// progress — those were removed. The category chip replaces genre.
class SeriesScreen extends ConsumerWidget {
  /// Creates the series page for [seriesId].
  const SeriesScreen({super.key, required this.seriesId});

  final String seriesId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(seriesDetailProvider(seriesId));
    return Scaffold(
      body: async.when(
        loading: () => const Center(child: BrainPulse(size: 28)),
        error: (e, _) => EmptyState(
          message: 'This series isn\'t available right now.',
          ctaLabel: 'Try again',
          onCta: () => ref.invalidate(seriesDetailProvider(seriesId)),
        ),
        data: (series) => _SeriesBody(series: series),
      ),
    );
  }
}

class _SeriesBody extends ConsumerStatefulWidget {
  const _SeriesBody({required this.series});
  final Series series;

  @override
  ConsumerState<_SeriesBody> createState() => _SeriesBodyState();
}

class _SeriesBodyState extends ConsumerState<_SeriesBody> {
  late bool _saved = widget.series.liked;

  void _play(int ep) => context.push('${Routes.storiesPlayer}?series=${widget.series.id}&ep=$ep');

  void _toggleSave() {
    final next = !_saved;
    setState(() => _saved = next);
    ref.read(storiesRepositoryProvider).postLike(
          contentType: 'series',
          contentId: widget.series.id,
          liked: next,
        );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final series = widget.series;
    final firstEp = series.episodes.isNotEmpty ? series.episodes.first : null;
    final season = firstEp?.seasonNumber ?? 1;

    return ListView(
      padding: EdgeInsets.zero,
      children: [
        // Hero banner.
        Stack(
          children: [
            AspectRatio(
              aspectRatio: 16 / 10,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  DecoratedBox(decoration: posterDecoration(series.title)),
                  posterHighlight(series.title),
                  Positioned.fill(child: PosterImage(url: series.posterUrl ?? series.thumbnailUrl)),
                  const DecoratedBox(decoration: BoxDecoration(gradient: cinematicScrim)),
                ],
              ),
            ),
            Positioned(
              top: MediaQuery.of(context).padding.top + 6,
              left: 4,
              child: IconButton(
                icon: const Icon(Icons.arrow_back, color: Colors.white),
                onPressed: () => context.pop(),
              ),
            ),
            Positioned(
              left: 16,
              right: 16,
              bottom: 14,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(series.title, style: AppText.display(26).copyWith(color: Colors.white, height: 1.15)),
                  const SizedBox(height: 6),
                  Text(
                    'SERIES · Season $season · ${series.effectiveEpisodeCount} Episodes',
                    style: AppText.mono(size: 12).copyWith(color: Colors.white.withValues(alpha: 0.6)),
                  ),
                ],
              ),
            ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: AppButton(
                      label: 'Play S${season}E${firstEp?.number ?? 1}',
                      icon: Icons.play_arrow_rounded,
                      expand: true,
                      onPressed: firstEp == null ? null : () => _play(firstEp.number),
                    ),
                  ),
                  const SizedBox(width: 10),
                  _SaveToggle(saved: _saved, onTap: _toggleSave),
                ],
              ),
              if ((series.premise ?? '').isNotEmpty) ...[
                const SizedBox(height: 16),
                Text(series.premise!, style: AppText.serif(size: 15).copyWith(color: c.textPrimary, height: 1.75)),
              ],
              const SizedBox(height: 16),
              if (series.episodes.isNotEmpty) ...[
                _SeasonSelector(season: season),
                const SizedBox(height: 4),
                for (final ep in series.episodes)
                  _EpisodeRow(
                    series: series,
                    episode: ep,
                    onTap: () => _play(ep.number),
                  ),
              ],
              const SizedBox(height: 24),
            ],
          ),
        ),
      ],
    );
  }
}

/// The Save-series 48px square toggle (plus → check/success).
class _SaveToggle extends StatelessWidget {
  const _SaveToggle({required this.saved, required this.onTap});
  final bool saved;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppDimens.inputRadius),
      child: Container(
        width: 48,
        height: 48,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(AppDimens.inputRadius),
          border: Border.all(color: saved ? c.success : c.borderMedium),
        ),
        child: Icon(saved ? Icons.check : Icons.add, size: 18, color: saved ? c.success : c.textPrimary),
      ),
    );
  }
}

/// The season selector (amber-active pill).
class _SeasonSelector extends StatelessWidget {
  const _SeasonSelector({required this.season});
  final int season;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      height: 32,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: c.brainAmberSurface,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: c.brainAmber),
      ),
      child: Text('Season $season', style: AppText.display(13).copyWith(color: c.brainAmber, fontWeight: FontWeight.w500)),
    );
  }
}

/// An episode list row: 16:9 thumb, `E1`, title, premise, duration.
class _EpisodeRow extends StatelessWidget {
  const _EpisodeRow({required this.series, required this.episode, required this.onTap});
  final Series series;
  final Episode episode;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final content = Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: SizedBox(
              width: 84,
              height: 54,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  DecoratedBox(decoration: posterDecoration('${series.title}${episode.number}')),
                  posterHighlight('${series.title}${episode.number}'),
                  Positioned.fill(child: PosterImage(url: episode.thumbnailUrl)),
                  if (episode.duration.isNotEmpty)
                    Positioned(
                      bottom: 3,
                      right: 3,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        decoration: BoxDecoration(color: Colors.black.withValues(alpha: 0.72), borderRadius: BorderRadius.circular(4)),
                        child: Text(episode.duration, style: AppText.mono(size: 9).copyWith(color: Colors.white)),
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    if (episode.processing)
                      const BrainPulse(size: 14)
                    else
                      Text('E${episode.number}', style: AppText.mono(size: 12).copyWith(color: c.textTertiary)),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(episode.title,
                          maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.md.copyWith(color: c.textPrimary, fontSize: 15)),
                    ),
                  ],
                ),
                if ((episode.premise ?? '').isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(episode.premise!,
                      maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.sm.copyWith(color: c.textSecondary)),
                ],
                if (episode.duration.isNotEmpty) ...[
                  const SizedBox(height: 5),
                  Text(episode.duration, style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                ],
              ],
            ),
          ),
        ],
      ),
    );

    return InkWell(
      onTap: episode.processing ? null : onTap,
      child: Container(
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: c.borderSubtle, width: 0.5)),
        ),
        child: content,
      ),
    );
  }
}
