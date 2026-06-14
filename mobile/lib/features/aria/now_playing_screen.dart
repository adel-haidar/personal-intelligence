import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/music.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../providers/aria_player_provider.dart';
import 'aria_widgets.dart';

/// The full-screen Now Playing view — the best-designed ARIA surface.
/// Ambient mood-tint background, album-art hero that scales on play/pause, an
/// amber like, a seekable waveform, transport, and Player | Lyrics tabs.
class NowPlayingScreen extends ConsumerStatefulWidget {
  /// Creates Now Playing.
  const NowPlayingScreen({super.key});

  @override
  ConsumerState<NowPlayingScreen> createState() => _NowPlayingScreenState();
}

class _NowPlayingScreenState extends ConsumerState<NowPlayingScreen> {
  int _tab = 0; // 0 = Player, 1 = Lyrics

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final s = ref.watch(ariaPlayerProvider);
    final p = ref.read(ariaPlayerProvider.notifier);
    final track = s.track;
    if (track == null) {
      return const Scaffold(body: Center(child: Text('Nothing playing')));
    }
    final total = track.totalSeconds;
    final cur = (total * s.progress / 100).round();
    final ambient = Color.alphaBlend(
      track.mood.color.withValues(alpha: c.isDark ? 0.25 : 0.15),
      c.backgroundPage,
    );

    void seekBy(int seconds) => p.seek(s.progress + seconds / total * 100);

    return Scaffold(
      backgroundColor: ambient,
      body: SafeArea(
        child: Column(
          children: [
            // Drag handle + collapse.
            Row(
              children: [
                IconButton(icon: const Icon(Icons.keyboard_arrow_down), onPressed: () => Navigator.of(context).maybePop()),
                Expanded(
                  child: Center(child: Text('Now playing', style: AppText.mono(size: 11).copyWith(color: c.textTertiary))),
                ),
                const SizedBox(width: 48),
              ],
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: AppDimens.space5),
                children: [
                  const SizedBox(height: AppDimens.space4),
                  Center(
                    child: AnimatedScale(
                      scale: s.playing ? 1.0 : 0.92,
                      duration: const Duration(milliseconds: 200),
                      curve: Curves.easeOut,
                      child: AlbumArt(title: track.title, mood: track.mood, size: 300, radius: 16, imageUrl: track.artUrl),
                    ),
                  ),
                  const SizedBox(height: AppDimens.space6),
                  Row(
                    children: [
                      Expanded(
                        child: Text(track.title, style: AppText.lg.copyWith(color: c.textPrimary)),
                      ),
                      _LikeButton(liked: s.isLiked(track.id), onTap: () => p.toggleLike(track.id)),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                        decoration: BoxDecoration(color: track.mood.color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(999)),
                        child: Text(track.mood.label, style: AppText.xs.copyWith(color: track.mood.color, fontWeight: FontWeight.w600)),
                      ),
                      const SizedBox(width: 8),
                      if (track.topicCategory.isNotEmpty)
                        Flexible(child: Text('from: ${track.topicCategory}', maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.sm.copyWith(color: c.textSecondary))),
                    ],
                  ),
                  const SizedBox(height: AppDimens.space5),
                  // Tabs.
                  Row(
                    children: [
                      _Tab(label: 'Player', active: _tab == 0, onTap: () => setState(() => _tab = 0)),
                      const SizedBox(width: AppDimens.space5),
                      _Tab(label: 'Lyrics', active: _tab == 1, onTap: () => setState(() => _tab = 1)),
                    ],
                  ),
                  const SizedBox(height: AppDimens.space4),
                  if (_tab == 0) ...[
                    Waveform(seed: track.title, progress: s.progress, onSeek: p.seek),
                    const SizedBox(height: 6),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(fmtTime(cur), style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                        Text(fmtTime(total), style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                      ],
                    ),
                    const SizedBox(height: AppDimens.space4),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                      children: [
                        IconButton(icon: const Icon(Icons.skip_previous), iconSize: 30, color: c.textSecondary, onPressed: p.prev),
                        _Seek10(label: '10', back: true, onTap: () => seekBy(-10)),
                        Container(
                          decoration: BoxDecoration(color: c.accentPrimary, shape: BoxShape.circle),
                          child: IconButton(
                            icon: Icon(s.playing ? Icons.pause : Icons.play_arrow, color: Colors.white),
                            iconSize: 34,
                            onPressed: p.toggle,
                          ),
                        ),
                        _Seek10(label: '10', back: false, onTap: () => seekBy(10)),
                        IconButton(icon: const Icon(Icons.skip_next), iconSize: 30, color: c.textSecondary, onPressed: p.next),
                      ],
                    ),
                    const SizedBox(height: AppDimens.space3),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        IconButton(
                          icon: const Icon(Icons.shuffle, size: 20),
                          color: s.shuffle ? c.accentPrimary : c.textTertiary,
                          onPressed: p.toggleShuffle,
                        ),
                        const SizedBox(width: AppDimens.space6),
                        IconButton(
                          icon: const Icon(Icons.repeat, size: 20),
                          color: s.repeat ? c.accentPrimary : c.textTertiary,
                          onPressed: p.toggleRepeat,
                        ),
                      ],
                    ),
                  ] else
                    _Lyrics(lines: track.lyrics),
                  const SizedBox(height: AppDimens.space5),
                  // Up next → queue.
                  if (s.queue.isNotEmpty)
                    GestureDetector(
                      onTap: () => _openQueue(context),
                      child: Container(
                        padding: const EdgeInsets.all(AppDimens.space3),
                        decoration: BoxDecoration(
                          color: c.backgroundSurface,
                          borderRadius: BorderRadius.circular(AppDimens.cardRadius),
                          border: Border.all(color: c.borderSubtle),
                        ),
                        child: Row(
                          children: [
                            Icon(Icons.queue_music, size: 18, color: c.textSecondary),
                            const SizedBox(width: AppDimens.space2),
                            Expanded(child: Text('Up next · ${s.queue.length} tracks', style: AppText.sm.copyWith(color: c.textSecondary))),
                            Icon(Icons.chevron_right, size: 18, color: c.textTertiary),
                          ],
                        ),
                      ),
                    ),
                  const SizedBox(height: AppDimens.space6),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _openQueue(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (_) => const _QueueSheet(),
    );
  }
}

class _Tab extends StatelessWidget {
  const _Tab({required this.label, required this.active, required this.onTap});
  final String label;
  final bool active;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return GestureDetector(
      onTap: onTap,
      child: Text(label, style: AppText.md.copyWith(color: active ? c.textPrimary : c.textTertiary)),
    );
  }
}

class _Seek10 extends StatelessWidget {
  const _Seek10({required this.label, required this.back, required this.onTap});
  final String label;
  final bool back;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return GestureDetector(
      onTap: onTap,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(back ? Icons.replay_10 : Icons.forward_10, size: 26, color: c.textSecondary),
        ],
      ),
    );
  }
}

class _LikeButton extends StatelessWidget {
  const _LikeButton({required this.liked, required this.onTap});
  final bool liked;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return IconButton(
      icon: Icon(liked ? Icons.favorite : Icons.favorite_border, color: liked ? c.brainAmber : c.textSecondary),
      iconSize: 26,
      onPressed: onTap,
    );
  }
}

class _Lyrics extends StatelessWidget {
  const _Lyrics({required this.lines});
  final List<String>? lines;
  @override
  Widget build(BuildContext context) {
    final c = context.c;
    if (lines == null || lines!.isEmpty) {
      return Text('No lyrics for this track.', style: AppText.serif(size: 15).copyWith(color: c.textTertiary));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final line in lines!)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(line, style: AppText.serif(size: 18).copyWith(color: c.textPrimary, height: 1.6)),
          ),
      ],
    );
  }
}

/// The queue bottom sheet — reorderable list with remove + clear.
class _QueueSheet extends ConsumerWidget {
  const _QueueSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final s = ref.watch(ariaPlayerProvider);
    final p = ref.read(ariaPlayerProvider.notifier);
    final tracks = s.queue.map(p.trackForId).whereType<Track>().toList();

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(AppDimens.space4, 0, AppDimens.space4, AppDimens.space4),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('Queue', style: AppText.md.copyWith(color: c.textPrimary)),
                const Spacer(),
                if (s.queue.isNotEmpty)
                  TextButton(onPressed: p.clearQueue, child: Text('Clear', style: AppText.sm.copyWith(color: c.danger))),
              ],
            ),
            if (s.track != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: AppDimens.space2),
                child: Row(
                  children: [
                    AlbumArt(title: s.track!.title, mood: s.track!.mood, size: 40, imageUrl: s.track!.artUrl),
                    const SizedBox(width: 10),
                    Expanded(child: Text(s.track!.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.base.copyWith(color: c.textPrimary))),
                    Text('Playing now', style: AppText.xs.copyWith(color: c.brainAmber)),
                  ],
                ),
              ),
            const Divider(),
            Flexible(
              child: tracks.isEmpty
                  ? Padding(
                      padding: const EdgeInsets.symmetric(vertical: AppDimens.space5),
                      child: Text('Nothing queued.', style: AppText.sm.copyWith(color: c.textTertiary)),
                    )
                  : ReorderableListView.builder(
                      shrinkWrap: true,
                      buildDefaultDragHandles: true,
                      itemCount: tracks.length,
                      onReorder: p.reorderQueue,
                      itemBuilder: (_, i) {
                        final t = tracks[i];
                        return Padding(
                          key: ValueKey('${t.id}-$i'),
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          child: Row(
                            children: [
                              AlbumArt(title: t.title, mood: t.mood, size: 36, imageUrl: t.artUrl),
                              const SizedBox(width: 10),
                              Expanded(child: Text(t.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.base.copyWith(color: c.textPrimary))),
                              Text(t.duration, style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                              IconButton(icon: Icon(Icons.close, size: 16, color: c.textTertiary), onPressed: () => p.dequeue(i)),
                            ],
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}
