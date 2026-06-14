import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_text_styles.dart';
import '../../providers/aria_player_provider.dart';
import 'aria_widgets.dart';

/// The persistent ARIA mini-player. Shown once a track has played this session
/// (until swiped away); reads app-level [ariaPlayerProvider] so playback and
/// the bar survive navigation. Mounted directly above the bottom nav in the
/// shell. Tap the art to open Now Playing; swipe down to dismiss.
class MiniPlayer extends ConsumerWidget {
  /// Creates the mini-player.
  const MiniPlayer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final s = ref.watch(ariaPlayerProvider);
    final p = ref.read(ariaPlayerProvider.notifier);
    final track = s.track;
    if (track == null || s.dismissed) return const SizedBox.shrink();

    final mood = track.mood;
    return GestureDetector(
      onVerticalDragEnd: (d) {
        if ((d.primaryVelocity ?? 0) > 0) p.dismiss();
      },
      child: Container(
        decoration: BoxDecoration(
          color: Color.alphaBlend(mood.color.withValues(alpha: c.isDark ? 0.12 : 0.06), c.backgroundSurface),
          border: Border(top: BorderSide(color: c.borderSubtle)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 2px amber progress bleeding across the very top.
            SizedBox(
              height: 2,
              child: LinearProgressIndicator(
                value: (s.progress / 100).clamp(0, 1),
                minHeight: 2,
                backgroundColor: Colors.transparent,
                valueColor: AlwaysStoppedAnimation(c.brainAmber),
              ),
            ),
            SizedBox(
              height: 58,
              child: Row(
                children: [
                  const SizedBox(width: 8),
                  GestureDetector(
                    onTap: () => context.push(Routes.ariaNow),
                    child: AlbumArt(title: track.title, mood: mood, size: 44, radius: 8, imageUrl: track.artUrl),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: GestureDetector(
                      onTap: () => context.push(Routes.ariaNow),
                      behavior: HitTestBehavior.opaque,
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                              style: AppText.md.copyWith(color: c.textPrimary)),
                          Text('${mood.label} · ${remainingLabel(track, s.progress)}',
                              maxLines: 1, overflow: TextOverflow.ellipsis,
                              style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                        ],
                      ),
                    ),
                  ),
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    icon: Icon(s.isLiked(track.id) ? Icons.favorite : Icons.favorite_border,
                        size: 20, color: s.isLiked(track.id) ? c.brainAmber : c.textSecondary),
                    onPressed: () => p.toggleLike(track.id),
                  ),
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    icon: Icon(s.playing ? Icons.pause : Icons.play_arrow, size: 26, color: c.accentPrimary),
                    onPressed: p.toggle,
                  ),
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    icon: Icon(Icons.skip_next, size: 24, color: c.textSecondary),
                    onPressed: p.next,
                  ),
                  const SizedBox(width: 4),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
