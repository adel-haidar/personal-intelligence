import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/seeded.dart';
import '../../core/widgets/brain_pulse.dart';

/// The cinematic overlay scrim (handoff token) for posters/banners where text
/// sits on image: a top-up fade from near-black.
///
/// `linear-gradient(to top, rgba(12,12,20,0.92), rgba(12,12,20,0.60) 40%, 0)`.
const cinematicScrim = LinearGradient(
  begin: Alignment.bottomCenter,
  end: Alignment.topCenter,
  colors: [
    Color(0xEB0C0C14), // 0.92
    Color(0x990C0C14), // 0.60 at 40%
    Color(0x000C0C14),
  ],
  stops: [0.0, 0.40, 1.0],
);

/// The 2:3 poster gradient seeded from a title — radial highlight + diagonal
/// wash into near-black (mirrors the prototype's `posterStyle`).
BoxDecoration posterDecoration(String seed) {
  final c = Seeded.color(seed);
  return BoxDecoration(
    gradient: LinearGradient(
      begin: const Alignment(-0.6, -1),
      end: const Alignment(0.4, 1),
      colors: [Color.alphaBlend(c.withValues(alpha: 0.35), const Color(0xFF0C0C14)), const Color(0xFF0C0C14)],
      stops: const [0.0, 0.92],
    ),
  );
}

/// The radial highlight layer drawn over [posterDecoration].
Widget posterHighlight(String seed) {
  final c = Seeded.color(seed);
  return DecoratedBox(
    decoration: BoxDecoration(
      gradient: RadialGradient(
        center: const Alignment(0.4, -0.76),
        radius: 1.0,
        colors: [c.withValues(alpha: 0.4), Colors.transparent],
        stops: const [0.0, 0.55],
      ),
    ),
  );
}

/// A cover image layer (`thumbnail_url` / `poster_url`) drawn over the seeded
/// gradient. Falls back silently to the gradient on null / error.
class PosterImage extends StatelessWidget {
  /// Creates a poster image layer for [url].
  const PosterImage({super.key, required this.url});
  final String? url;

  @override
  Widget build(BuildContext context) {
    final u = url;
    if (u == null || u.isEmpty) return const SizedBox.shrink();
    return CachedNetworkImage(
      imageUrl: u,
      fit: BoxFit.cover,
      placeholder: (_, __) => const SizedBox.shrink(),
      errorWidget: (_, __, ___) => const SizedBox.shrink(),
    );
  }
}

/// A mono genre chip on the amber surface (≤8 chars).
class GenreChip extends StatelessWidget {
  /// Creates a genre chip.
  const GenreChip({super.key, required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      height: 22,
      padding: const EdgeInsets.symmetric(horizontal: 9),
      alignment: Alignment.center,
      decoration: BoxDecoration(color: c.brainAmberSurface, borderRadius: BorderRadius.circular(999)),
      child: Text(label, style: AppText.mono(size: 11).copyWith(color: c.brainAmber)),
    );
  }
}

/// The "From your brain" panel — amber topic chips.
class BrainConnection extends StatelessWidget {
  /// Creates a brain-connection panel for [topics].
  const BrainConnection({super.key, required this.topics});
  final List<String> topics;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('From your brain', style: AppText.label.copyWith(color: c.textTertiary, letterSpacing: 0.6)),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final t in topics)
              Container(
                height: 28,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                alignment: Alignment.center,
                decoration: BoxDecoration(color: c.brainAmberSurface, borderRadius: BorderRadius.circular(999)),
                child: Text(t, style: AppText.sm.copyWith(color: c.brainAmber)),
              ),
          ],
        ),
      ],
    );
  }
}

/// A poster card (2:3) — the poster-first building block used everywhere except
/// the player and episode list. Shows genre/duration/SERIES chips, a title
/// treatment, an optional amber progress bar, and a sub line below.
class StoryPoster extends StatelessWidget {
  /// Creates a poster card.
  const StoryPoster({
    super.key,
    required this.seed,
    required this.title,
    required this.onTap,
    this.width = 140,
    this.genre,
    this.duration,
    this.isSeries = false,
    this.processing = false,
    this.progress,
    this.subLabel,
    this.subColor,
    this.subIsMono = false,
    this.showProgressOnly = false,
    this.imageUrl,
  });

  /// Seed for the gradient + the on-art title treatment text.
  final String seed;

  /// Optional cover image (`thumbnail_url` / `poster_url`).
  final String? imageUrl;

  /// Card title (below the poster). Empty when [processing].
  final String title;
  final VoidCallback onTap;
  final double width;
  final String? genre;
  final String? duration;
  final bool isSeries;
  final bool processing;

  /// 0–100 progress for the amber bar at the poster bottom.
  final int? progress;

  /// Sub line under the title (score / "N episodes" / "22m left").
  final String? subLabel;
  final Color? subColor;
  final bool subIsMono;

  /// True for Continue-watching cards (no genre/score, only progress + left).
  final bool showProgressOnly;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return GestureDetector(
      onTap: processing ? null : onTap,
      child: SizedBox(
        width: width == double.infinity ? null : width,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: AspectRatio(
                aspectRatio: 2 / 3,
                child: processing
                    ? Container(
                        color: c.brainAmberSurface,
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const BrainPulse(size: 24),
                            const SizedBox(height: 6),
                            Text('Generating…', style: AppText.xs.copyWith(color: c.textSecondary)),
                          ],
                        ),
                      )
                    : Stack(
                        fit: StackFit.expand,
                        children: [
                          DecoratedBox(decoration: posterDecoration(seed)),
                          posterHighlight(seed),
                          Positioned.fill(child: PosterImage(url: imageUrl)),
                          const DecoratedBox(decoration: BoxDecoration(gradient: cinematicScrim)),
                          if (genre != null && genre!.isNotEmpty)
                            Positioned(top: 7, left: 7, child: GenreChip(label: genre!)),
                          if (isSeries)
                            Positioned(
                              top: 7,
                              right: 7,
                              child: _pill(c, 'SERIES'),
                            )
                          else if (duration != null && duration!.isNotEmpty)
                            Positioned(bottom: 7, right: 7, child: _pill(c, duration!)),
                          Positioned(
                            left: 10,
                            right: 10,
                            bottom: 14,
                            child: Text(
                              title,
                              maxLines: 3,
                              overflow: TextOverflow.ellipsis,
                              style: AppText.display(13).copyWith(color: Colors.white, height: 1.2),
                            ),
                          ),
                          if (progress != null)
                            Positioned(
                              left: 0,
                              right: 0,
                              bottom: 0,
                              child: _PosterProgress(progress: progress!),
                            ),
                        ],
                      ),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              processing ? 'New film' : title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppText.sm.copyWith(color: c.textPrimary, fontWeight: FontWeight.w500),
            ),
            if (!processing && subLabel != null) ...[
              const SizedBox(height: 3),
              Text(
                subLabel!,
                style: (subIsMono ? AppText.mono(size: 11) : AppText.sm).copyWith(color: subColor ?? c.textSecondary),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _pill(AppPalette c, String text) {
    final isSeriesPill = text == 'SERIES';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
      decoration: BoxDecoration(
        color: isSeriesPill ? c.brainAmberSurface : Colors.black.withValues(alpha: 0.7),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        style: AppText.mono(size: 10).copyWith(color: isSeriesPill ? c.brainAmber : Colors.white),
      ),
    );
  }
}

/// The thin amber progress bar bleeding across a poster bottom.
class _PosterProgress extends StatelessWidget {
  const _PosterProgress({required this.progress});
  final int progress;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return SizedBox(
      height: 3,
      child: Stack(
        children: [
          Positioned.fill(child: ColoredBox(color: Colors.black.withValues(alpha: 0.4))),
          FractionallySizedBox(
            widthFactor: (progress / 100).clamp(0.0, 1.0),
            child: ColoredBox(color: c.brainAmber),
          ),
        ],
      ),
    );
  }
}

/// The featured, letterboxed landscape hero (subtle 4% black bars top/bottom).
class StoriesHero extends StatelessWidget {
  /// Creates the featured hero.
  const StoriesHero({
    super.key,
    required this.seed,
    this.genre,
    required this.title,
    required this.premise,
    required this.metaTrailing,
    required this.onPlay,
    required this.onOpen,
    this.imageUrl,
  });

  final String seed;

  /// Category chip label (≤8 chars). Omitted when null.
  final String? genre;
  final String title;
  final String premise;

  /// Mono meta, e.g. "24:18".
  final String metaTrailing;
  final VoidCallback onPlay;
  final VoidCallback onOpen;

  /// Optional cover image.
  final String? imageUrl;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onOpen,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 220),
          child: Stack(
            children: [
              Positioned.fill(child: DecoratedBox(decoration: posterDecoration(seed))),
              Positioned.fill(child: posterHighlight(seed)),
              Positioned.fill(child: PosterImage(url: imageUrl)),
              const Positioned.fill(child: DecoratedBox(decoration: BoxDecoration(gradient: cinematicScrim))),
              // 4% letterbox bars.
              const Positioned(top: 0, left: 0, right: 0, child: SizedBox(height: 9, child: ColoredBox(color: Colors.black))),
              const Positioned(bottom: 0, left: 0, right: 0, child: SizedBox(height: 9, child: ColoredBox(color: Colors.black))),
              if (genre != null && genre!.isNotEmpty) Positioned(top: 16, left: 12, child: GenreChip(label: genre!)),
              Positioned(
                top: 18,
                right: 14,
                child: Text('FILM', style: AppText.mono(size: 11).copyWith(color: Colors.white.withValues(alpha: 0.72))),
              ),
              Positioned.fill(
                child: Center(
                  child: GestureDetector(
                    onTap: onPlay,
                    child: Container(
                      width: 52,
                      height: 52,
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.22),
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.white.withValues(alpha: 0.3)),
                      ),
                      child: const Icon(Icons.play_arrow_rounded, color: Colors.white, size: 26),
                    ),
                  ),
                ),
              ),
              Positioned(
                left: 16,
                right: 16,
                bottom: 20,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, maxLines: 2, overflow: TextOverflow.ellipsis, style: AppText.display(22).copyWith(color: Colors.white, height: 1.15)),
                    const SizedBox(height: 6),
                    Text(
                      premise,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.serif(size: 13).copyWith(color: Colors.white.withValues(alpha: 0.8)),
                    ),
                    const SizedBox(height: 8),
                    Text(metaTrailing, style: AppText.mono(size: 11).copyWith(color: Colors.white.withValues(alpha: 0.7))),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
