import 'dart:math' as math;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../../core/models/music.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/seeded.dart';

/// Formats whole seconds as `m:ss`.
String fmtTime(int seconds) {
  final s = seconds.clamp(0, 86400);
  return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
}

/// Remaining-time label for a track at [progress] (0–100), e.g. "2:14 left".
String remainingLabel(Track track, double progress) {
  final total = track.totalSeconds;
  final left = (total * (1 - progress / 100)).round();
  return '${fmtTime(left)} left';
}

/// Square AI album art. Uses the backend `art_url` (via CachedNetworkImage) when
/// present; otherwise falls back to a deterministic colour-field seeded from
/// title + mood. 1:1, no shadow in dark, 0.5px border in light (per the handoff).
class AlbumArt extends StatelessWidget {
  /// Creates album art for [title] in [mood], optionally backed by [imageUrl].
  const AlbumArt({super.key, required this.title, required this.mood, this.size, this.radius = 12, this.imageUrl});

  final String title;
  final Mood mood;
  final double? size;
  final double radius;

  /// Optional remote art URL (`art_url`); falls back to the seeded gradient.
  final String? imageUrl;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final seed = Seeded.color(title.isEmpty ? mood.label : title);
    final gradient = BoxDecoration(
      borderRadius: BorderRadius.circular(radius),
      border: c.isDark ? null : Border.all(color: c.borderSubtle, width: 0.5),
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          Color.alphaBlend(mood.color.withValues(alpha: 0.55), seed),
          Color.alphaBlend(seed.withValues(alpha: 0.65), mood.color),
        ],
      ),
    );
    final url = imageUrl;
    if (url == null || url.isEmpty) {
      return Container(width: size, height: size, decoration: gradient);
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: CachedNetworkImage(
        imageUrl: url,
        width: size,
        height: size,
        fit: BoxFit.cover,
        placeholder: (_, __) => Container(width: size, height: size, decoration: gradient),
        errorWidget: (_, __, ___) => Container(width: size, height: size, decoration: gradient),
      ),
    );
  }
}

/// A mood filter pill. Never plain grey: inactive = mood-coloured text + border,
/// active = filled with the mood colour + white text. "All" uses the accent.
class MoodChip extends StatelessWidget {
  /// Creates a mood chip. Pass [color] = null for the neutral "All" accent chip.
  const MoodChip({super.key, required this.label, required this.active, required this.onTap, this.color});

  final String label;
  final bool active;
  final VoidCallback onTap;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final tint = color ?? c.accentPrimary;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: active ? tint : Colors.transparent,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: tint),
        ),
        child: Text(label,
            style: AppText.display(13).copyWith(
              color: active ? Colors.white : tint,
              fontWeight: FontWeight.w500,
            )),
      ),
    );
  }
}

/// A seekable waveform. Played portion = accent, unplayed = borderMedium. 48px.
class Waveform extends StatelessWidget {
  /// Creates a waveform at [progress] (0–100); [onSeek] receives a 0–100 percent.
  const Waveform({super.key, required this.seed, required this.progress, required this.onSeek, this.height = 48});

  final String seed;
  final double progress;
  final ValueChanged<double> onSeek;
  final double height;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return SizedBox(
      height: height,
      child: LayoutBuilder(
        builder: (context, box) {
          void seekAt(Offset local) => onSeek((local.dx / box.maxWidth * 100).clamp(0, 100));
          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapDown: (d) => seekAt(d.localPosition),
            onHorizontalDragUpdate: (d) => seekAt(d.localPosition),
            child: CustomPaint(
              size: Size(box.maxWidth, height),
              painter: _WaveformPainter(
                seed: seed,
                progress: progress,
                played: c.accentPrimary,
                unplayed: c.borderMedium,
              ),
            ),
          );
        },
      ),
    );
  }
}

class _WaveformPainter extends CustomPainter {
  _WaveformPainter({required this.seed, required this.progress, required this.played, required this.unplayed});

  final String seed;
  final double progress;
  final Color played;
  final Color unplayed;

  @override
  void paint(Canvas canvas, Size size) {
    const barW = 3.0;
    const gap = 2.0;
    final count = (size.width / (barW + gap)).floor();
    if (count <= 0) return;
    final rng = math.Random(seed.hashCode);
    final playedCount = (count * progress / 100).round();
    for (var i = 0; i < count; i++) {
      final h = (0.18 + rng.nextDouble() * 0.82) * size.height;
      final x = i * (barW + gap);
      final y = (size.height - h) / 2;
      final paint = Paint()..color = i <= playedCount ? played : unplayed;
      canvas.drawRRect(
        RRect.fromRectAndRadius(Rect.fromLTWH(x, y, barW, h), const Radius.circular(1.5)),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(_WaveformPainter old) => old.progress != progress || old.played != played;
}
