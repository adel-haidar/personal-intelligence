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
import '../signal/signal_cards.dart' show SectionHead;
import 'stories_widgets.dart';

/// Film detail — landscape key visual, duration meta, Play/Continue, Premise.
/// Backed by `GET /api/stories/films/{id}` (FilmDetail).
///
/// The backend exposes no score, year, topics, or "why" — those panels were
/// removed. The category chip replaces the old genre chip.
class FilmDetailScreen extends ConsumerWidget {
  /// Creates the film detail screen for [filmId].
  const FilmDetailScreen({super.key, required this.filmId});

  final String filmId;

  void _play(BuildContext context, Film f) => context.push('${Routes.storiesPlayer}?film=${f.id}');

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(filmDetailProvider(filmId));
    return Scaffold(
      body: async.when(
        loading: () => const Center(child: BrainPulse(size: 28)),
        error: (e, _) => EmptyState(
          message: 'This film isn\'t available right now.',
          ctaLabel: 'Try again',
          onCta: () => ref.invalidate(filmDetailProvider(filmId)),
        ),
        data: (film) => _FilmBody(film: film, onPlay: () => _play(context, film)),
      ),
    );
  }
}

class _FilmBody extends StatelessWidget {
  const _FilmBody({required this.film, required this.onPlay});
  final Film film;
  final VoidCallback onPlay;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final wp = film.watchProgress;
    final started = film.started;

    return ListView(
      padding: EdgeInsets.zero,
      children: [
        // Landscape key visual.
        Stack(
          children: [
            AspectRatio(
              aspectRatio: 16 / 9,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  DecoratedBox(decoration: posterDecoration(film.title)),
                  posterHighlight(film.title),
                  Positioned.fill(child: PosterImage(url: film.posterUrl ?? film.thumbnailUrl)),
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
                  if (film.categoryChip != null) ...[
                    GenreChip(label: film.categoryChip!),
                    const SizedBox(height: 8),
                  ],
                  Text(film.title, style: AppText.display(22).copyWith(color: Colors.white, height: 1.2)),
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
              if (film.duration.isNotEmpty) ...[
                Text(
                  film.duration,
                  style: AppText.mono(size: 12).copyWith(color: c.textSecondary),
                ),
                const SizedBox(height: 16),
              ],
              if (film.processing) ...[
                _ProcessingNotice(),
              ] else ...[
                if (started && wp?.percent != null) ...[
                  _AmberProgress(progress: wp!.percent!),
                  const SizedBox(height: 8),
                ],
                SizedBox(
                  width: double.infinity,
                  child: started
                      ? _ContinueButton(
                          label: wp?.resumeLabel.isNotEmpty ?? false
                              ? 'Continue from ${wp!.resumeLabel}'
                              : 'Continue',
                          onTap: onPlay)
                      : AppButton(label: 'Play', icon: Icons.play_arrow_rounded, expand: true, onPressed: onPlay),
                ),
              ],
              if ((film.premise ?? '').isNotEmpty) ...[
                const SizedBox(height: 16),
                Text('Premise', style: AppText.label.copyWith(color: c.textTertiary, letterSpacing: 0.6)),
                const SizedBox(height: 8),
                Text(film.premise!, style: AppText.serif(size: 15).copyWith(color: c.textPrimary, height: 1.75)),
              ],
            ],
          ),
        ),
        if (film.related.isNotEmpty) ...[
          const SectionHead(title: 'More like this'),
          _MoreLikeThis(related: film.related),
        ],
        const SizedBox(height: 24),
      ],
    );
  }
}

/// The "still generating" treatment (replaces the Play button while rendering).
class _ProcessingNotice extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 20),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: c.brainAmberSurface,
        borderRadius: BorderRadius.circular(AppDimens.cardRadius),
      ),
      child: Column(
        children: [
          const BrainPulse(size: 26),
          const SizedBox(height: 8),
          Text('Generating…', style: AppText.sm.copyWith(color: c.textSecondary)),
        ],
      ),
    );
  }
}

/// More-like-this poster row from the detail `related` list.
class _MoreLikeThis extends StatelessWidget {
  const _MoreLikeThis({required this.related});
  final List<Film> related;

  @override
  Widget build(BuildContext context) {
    final list = related.where((f) => !f.processing).take(6).toList();
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(16, 2, 16, 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < list.length; i++) ...[
            if (i > 0) const SizedBox(width: 12),
            StoryPoster(
              seed: list[i].title,
              title: list[i].title,
              genre: list[i].categoryChip,
              duration: list[i].duration,
              imageUrl: list[i].posterUrl ?? list[i].thumbnailUrl,
              onTap: () => context.push('${Routes.stories}/film/${list[i].id}'),
            ),
          ],
        ],
      ),
    );
  }
}

/// A thin amber progress bar (detail / series action area).
class _AmberProgress extends StatelessWidget {
  const _AmberProgress({required this.progress});
  final int progress;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return ClipRRect(
      borderRadius: BorderRadius.circular(2),
      child: SizedBox(
        height: 4,
        child: Stack(
          children: [
            Positioned.fill(child: ColoredBox(color: c.borderMedium)),
            FractionallySizedBox(
              widthFactor: (progress / 100).clamp(0.0, 1.0),
              child: ColoredBox(color: c.brainAmber),
            ),
          ],
        ),
      ),
    );
  }
}

/// An amber-fill "Continue" CTA button.
class _ContinueButton extends StatelessWidget {
  const _ContinueButton({required this.label, required this.onTap});
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return FilledButton(
      onPressed: onTap,
      style: FilledButton.styleFrom(
        backgroundColor: c.brainAmber,
        foregroundColor: const Color(0xFF1C1B2E),
        minimumSize: const Size(0, 48),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppDimens.inputRadius)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.play_arrow_rounded, size: 18, color: Color(0xFF1C1B2E)),
          const SizedBox(width: AppDimens.space2),
          Flexible(
            child: Text(label,
                maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.button.copyWith(color: const Color(0xFF1C1B2E))),
          ),
        ],
      ),
    );
  }
}
