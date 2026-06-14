import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../../core/models/video.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/seeded.dart';
import '../../core/widgets/brain_pulse.dart';
import '../../core/widgets/creator_avatar.dart';
import '../../core/widgets/feed_chip.dart';
import '../../core/widgets/featured_hero.dart';
import '../../core/widgets/score_badge.dart';

/// A seeded/real thumbnail with a duration badge, optional progress bar, and a
/// "Rendering…" overlay while processing. Shared by the SIGNAL cards.
class VideoThumb extends StatelessWidget {
  /// Creates a thumbnail for [video].
  const VideoThumb({super.key, required this.video, this.radius = 8, this.playOverlaySize});

  final Video video;
  final double radius;

  /// When set, draws a centered play button of this size (wide card).
  final double? playOverlaySize;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final hasImage = video.thumbnailUrl != null && video.thumbnailUrl!.isNotEmpty;
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: AspectRatio(
        aspectRatio: 16 / 9,
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (hasImage)
              CachedNetworkImage(
                imageUrl: video.thumbnailUrl!,
                fit: BoxFit.cover,
                placeholder: (_, __) => DecoratedBox(decoration: Seeded.thumb(video.creatorName, c.backgroundRaised)),
                errorWidget: (_, __, ___) => DecoratedBox(decoration: Seeded.thumb(video.creatorName, c.backgroundRaised)),
              )
            else
              DecoratedBox(decoration: Seeded.thumb(video.creatorName, c.backgroundRaised)),
            if (video.isProcessing)
              Container(
                color: c.brainAmberSurface.withValues(alpha: 0.85),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const BrainPulse(size: 24),
                    const SizedBox(height: 4),
                    Text('Rendering…', style: AppText.xs.copyWith(color: c.textSecondary)),
                  ],
                ),
              )
            else ...[
              if (playOverlaySize != null) Center(child: HeroPlayButton(size: playOverlaySize!)),
              if (video.durationLabel.isNotEmpty)
                Positioned(
                  top: 6,
                  right: 6,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                      color: Colors.black.withValues(alpha: 0.78),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(video.durationLabel, style: AppText.mono(size: 10).copyWith(color: Colors.white)),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

/// The standard 180px (default) horizontal video card. The whole card is the
/// tap target; no action buttons.
class VideoRowCard extends StatelessWidget {
  /// Creates a video card.
  const VideoRowCard({super.key, required this.video, required this.onTap, this.width = 180});

  final Video video;
  final VoidCallback onTap;
  final double width;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return GestureDetector(
      onTap: video.isProcessing ? null : onTap,
      child: SizedBox(
        width: width,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            VideoThumb(video: video),
            const SizedBox(height: 8),
            Text(video.title, maxLines: 2, overflow: TextOverflow.ellipsis,
                style: AppText.sm.copyWith(color: c.textPrimary, fontWeight: FontWeight.w500, height: 1.35)),
            const SizedBox(height: 4),
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${video.creatorName.split(' ').first} · ${video.durationLabel}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppText.mono(size: 11).copyWith(color: c.textTertiary),
                  ),
                ),
                if (!video.isProcessing) ScoreText(score: video.score),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// A full-width "wide" card used when a category has a single video.
class WideVideoCard extends StatelessWidget {
  /// Creates a wide card.
  const WideVideoCard({super.key, required this.video, required this.onTap});

  final Video video;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return GestureDetector(
      onTap: video.isProcessing ? null : onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          VideoThumb(video: video, radius: 10, playOverlaySize: 44),
          const SizedBox(height: 10),
          Text(video.title, style: AppText.display(16).copyWith(color: c.textPrimary, height: 1.3)),
          const SizedBox(height: 6),
          Row(
            children: [
              CreatorAvatar(name: video.creatorName, imageUrl: video.creatorAvatar, size: 20),
              const SizedBox(width: 8),
              Expanded(child: Text(video.creatorName, style: AppText.sm.copyWith(color: c.textSecondary), maxLines: 1, overflow: TextOverflow.ellipsis)),
              ScoreText(score: video.score),
              if (video.category != null) ...[
                const SizedBox(width: 8),
                FeedChip(label: video.category!, active: false, onTap: () {}),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

/// The SIGNAL featured hero with a play button (or processing state).
class FeaturedVideoHero extends StatelessWidget {
  /// Creates the featured video hero.
  const FeaturedVideoHero({super.key, required this.video, required this.onPlay});

  final Video video;
  final VoidCallback onPlay;

  @override
  Widget build(BuildContext context) {
    return FeaturedHero(
      seedName: video.creatorName,
      imageUrl: video.thumbnailUrl,
      onTap: video.isProcessing ? null : onPlay,
      topLeft: FeedChip(label: video.category ?? 'Signal', active: true, onTap: () {}),
      topRight: Text(video.durationLabel,
          style: AppText.mono(size: 11).copyWith(color: Colors.white)),
      center: video.isProcessing
          ? Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const BrainPulse(size: 28),
                const SizedBox(height: 6),
                Text('Rendering…', style: AppText.sm.copyWith(color: Colors.white)),
              ],
            )
          : const HeroPlayButton(),
      title: video.title,
      metaName: video.creatorName,
      metaTrailing: '· ${video.scoreLabel}',
    );
  }
}

/// A section header: an optional 3px accent bar + title, with optional See-all.
class SectionHead extends StatelessWidget {
  /// Creates a section header.
  const SectionHead({super.key, required this.title, this.accent = false, this.onSeeAll});

  final String title;
  final bool accent;
  final VoidCallback? onSeeAll;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 22, 16, 10),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              if (accent) ...[
                Container(width: 3, height: 15, decoration: BoxDecoration(color: c.accentPrimary, borderRadius: BorderRadius.circular(2))),
                const SizedBox(width: 8),
              ],
              Text(title, style: AppText.display(15).copyWith(color: c.textPrimary)),
            ],
          ),
          if (onSeeAll != null)
            GestureDetector(
              onTap: onSeeAll,
              child: Text('See all →', style: AppText.sm.copyWith(color: c.accentPrimary)),
            ),
        ],
      ),
    );
  }
}

/// The standard 16px-gutter horizontal scroll row holding video cards.
class VideoRow extends StatelessWidget {
  /// Creates a horizontal video row.
  const VideoRow({super.key, required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(16, 2, 16, 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const SizedBox(width: 12),
            children[i],
          ],
        ],
      ),
    );
  }
}
