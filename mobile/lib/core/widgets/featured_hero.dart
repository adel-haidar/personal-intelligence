import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';
import '../utils/seeded.dart';

/// The full-width editorial hero shared by PULSE and SIGNAL.
///
/// Background is the real image full-bleed, or a seeded gradient over
/// `background.raised`. A bottom scrim keeps overlay text legible (always
/// white). Slots: [topLeft]/[topRight] (absolute top row), an optional [center]
/// (play button / processing), and the title + meta body.
class FeaturedHero extends StatelessWidget {
  /// Creates a hero.
  const FeaturedHero({
    super.key,
    required this.seedName,
    required this.title,
    required this.metaName,
    required this.metaTrailing,
    this.imageUrl,
    this.topLeft,
    this.topRight,
    this.center,
    this.onTap,
  });

  final String seedName;
  final String title;
  final String metaName;

  /// One-line trailing mono meta, e.g. "· 4 min read" or "· 0.79".
  final String metaTrailing;
  final String? imageUrl;
  final Widget? topLeft;
  final Widget? topRight;
  final Widget? center;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final seed = Seeded.color(seedName);
    final scrim = c.isDark ? const Color(0xDB08080E) : const Color(0xC21C1B2E);
    final hasImage = imageUrl != null && imageUrl!.isNotEmpty;

    return GestureDetector(
      onTap: onTap,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: Container(
          constraints: const BoxConstraints(minHeight: 200),
          color: c.backgroundRaised,
          child: Stack(
            children: [
              // Background: real image, else seeded radial + linear wash.
              Positioned.fill(
                child: hasImage
                    ? CachedNetworkImage(
                        imageUrl: imageUrl!,
                        fit: BoxFit.cover,
                        placeholder: (_, __) => _seedBg(seed, c.backgroundRaised),
                        errorWidget: (_, __, ___) => _seedBg(seed, c.backgroundRaised),
                      )
                    : _seedBg(seed, c.backgroundRaised),
              ),
              // Scrim for legibility.
              Positioned.fill(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [Colors.transparent, scrim],
                      stops: const [0.28, 1.0],
                    ),
                  ),
                ),
              ),
              if (topLeft != null) Positioned(top: 12, left: 12, child: topLeft!),
              if (topRight != null) Positioned(top: 12, right: 12, child: topRight!),
              if (center != null) Positioned.fill(child: Center(child: center!)),
              // Body.
              Positioned(
                left: 16,
                right: 16,
                bottom: 16,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.display(18).copyWith(color: Colors.white, height: 1.25),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            metaName,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppText.display(13).copyWith(
                                color: Colors.white.withValues(alpha: 0.72), fontWeight: FontWeight.w500),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          metaTrailing,
                          style: AppText.mono(size: 11).copyWith(color: Colors.white.withValues(alpha: 0.72)),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _seedBg(Color seed, Color raised) {
    return Stack(
      children: [
        Positioned.fill(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: const Alignment(-0.7, -0.9),
                end: const Alignment(0.6, 1),
                colors: [Color.alphaBlend(seed.withValues(alpha: 0.25), raised), raised],
              ),
            ),
          ),
        ),
        Positioned.fill(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: RadialGradient(
                center: const Alignment(-0.45, -0.55),
                radius: 0.9,
                colors: [seed.withValues(alpha: 0.4), Colors.transparent],
                stops: const [0.0, 0.62],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// The 52px circular translucent play button used on video heroes.
class HeroPlayButton extends StatelessWidget {
  /// Creates a play button of [size] px.
  const HeroPlayButton({super.key, this.size = 52});
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.22),
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white.withValues(alpha: 0.3)),
      ),
      child: Icon(Icons.play_arrow_rounded, color: Colors.white, size: size * 0.5),
    );
  }
}
