import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/music.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/states.dart';
import '../../providers/aria_player_provider.dart';
import 'aria_widgets.dart';

/// Playlist / album detail — centered art, meta, Save/Play/Shuffle, and a track
/// list where the playing row gets a 3px accent border + amber tint. API-backed.
class PlaylistDetailScreen extends ConsumerWidget {
  /// Creates the detail screen for [playlistId].
  const PlaylistDetailScreen({super.key, required this.playlistId});

  final String playlistId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(playlistDetailProvider(playlistId));
    return Scaffold(
      appBar: AppBar(),
      body: async.when(
        loading: () => const ShimmerList(),
        error: (e, _) => ErrorRetry(
          message: 'This playlist isn\'t available.',
          onRetry: () => ref.invalidate(playlistDetailProvider(playlistId)),
        ),
        data: (pl) => _PlaylistBody(playlist: pl),
      ),
    );
  }
}

class _PlaylistBody extends ConsumerWidget {
  const _PlaylistBody({required this.playlist});
  final Playlist playlist;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final pl = playlist;
    final tracks = pl.tracks;
    final s = ref.watch(ariaPlayerProvider);
    final p = ref.read(ariaPlayerProvider.notifier);
    final ids = tracks.map((t) => t.id).toList();

    return ListView(
      padding: const EdgeInsets.fromLTRB(AppDimens.space5, 0, AppDimens.space5, AppDimens.space8),
      children: [
        Center(child: AlbumArt(title: pl.title, mood: pl.mood, size: 220, radius: 16, imageUrl: pl.artUrl)),
        const SizedBox(height: AppDimens.space5),
        Text(pl.title, textAlign: TextAlign.center, style: AppText.lg.copyWith(color: c.textPrimary)),
        const SizedBox(height: 6),
        Center(
          child: Text('${pl.effectiveTrackCount} tracks · ${pl.totalLabel}',
              style: AppText.mono(size: 12).copyWith(color: c.textTertiary)),
        ),
        const SizedBox(height: AppDimens.space5),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            AppButton(label: 'Save', variant: AppButtonVariant.outlined, icon: Icons.favorite_border, onPressed: () {}),
            const SizedBox(width: AppDimens.space3),
            AppButton(
              label: 'Play',
              icon: Icons.play_arrow,
              onPressed: tracks.isEmpty ? null : () => p.playTrack(tracks.first, queueIds: ids),
            ),
            const SizedBox(width: AppDimens.space3),
            AppButton(label: 'Shuffle', variant: AppButtonVariant.outlined, icon: Icons.shuffle, onPressed: () {
              p.toggleShuffle();
              if (tracks.isNotEmpty) p.playTrack(tracks.first, queueIds: ids);
            }),
          ],
        ),
        const SizedBox(height: AppDimens.space5),
        if (tracks.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: AppDimens.space6),
            child: Text('No tracks in this playlist yet.',
                textAlign: TextAlign.center, style: AppText.serif(size: 15).copyWith(color: c.textTertiary)),
          )
        else
          for (var i = 0; i < tracks.length; i++)
            _TrackRow(
              index: i + 1,
              track: tracks[i],
              playing: s.track?.id == tracks[i].id,
              isPlayingNow: s.track?.id == tracks[i].id && s.playing,
              liked: s.isLiked(tracks[i].id),
              onTap: () => p.playTrack(tracks[i], queueIds: ids),
              onLike: () => p.toggleLike(tracks[i].id),
            ),
      ],
    );
  }
}

class _TrackRow extends StatelessWidget {
  const _TrackRow({
    required this.index,
    required this.track,
    required this.playing,
    required this.isPlayingNow,
    required this.liked,
    required this.onTap,
    required this.onLike,
  });
  final int index;
  final Track track;
  final bool playing;
  final bool isPlayingNow;
  final bool liked;
  final VoidCallback onTap;
  final VoidCallback onLike;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      decoration: BoxDecoration(
        color: playing ? Color.alphaBlend(c.brainAmber.withValues(alpha: 0.08), c.backgroundPage) : null,
        border: Border(
          left: BorderSide(color: playing ? c.accentPrimary : Colors.transparent, width: 3),
          bottom: BorderSide(color: c.borderSubtle, width: 0.5),
        ),
      ),
      child: ListTile(
        onTap: onTap,
        contentPadding: const EdgeInsets.only(left: 10, right: 0),
        leading: SizedBox(
          width: 44,
          child: Center(
            child: playing
                ? Icon(isPlayingNow ? Icons.pause : Icons.play_arrow, color: c.accentPrimary, size: 20)
                : Text('$index', style: AppText.mono(size: 13).copyWith(color: c.textTertiary)),
          ),
        ),
        title: Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.base.copyWith(color: c.textPrimary)),
        subtitle: Text(track.mood.label, style: AppText.xs.copyWith(color: track.mood.color)),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (track.duration.isNotEmpty)
              Text(track.duration, style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
            IconButton(
              icon: Icon(liked ? Icons.favorite : Icons.favorite_border, size: 18, color: liked ? c.brainAmber : c.textSecondary),
              onPressed: onLike,
            ),
          ],
        ),
      ),
    );
  }
}
