import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/music.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/brain_pulse.dart';
import '../../core/widgets/masthead.dart';
import '../../core/widgets/states.dart';
import '../../providers/aria_player_provider.dart';
import 'aria_widgets.dart';

/// ARIA library — mood filter, now-playing hero, playlists, new tracks, the
/// signature "From your brain" section, and by-mood rows. API-backed.
class AriaLibraryScreen extends ConsumerStatefulWidget {
  /// Creates the ARIA library.
  const AriaLibraryScreen({super.key});

  @override
  ConsumerState<AriaLibraryScreen> createState() => _AriaLibraryScreenState();
}

class _AriaLibraryScreenState extends ConsumerState<AriaLibraryScreen> {
  Mood? _mood; // null = All

  void _playTrack(Track t, List<Track> ready) {
    if (t.processing) return;
    ref.read(ariaPlayerProvider.notifier).playTrack(
          t,
          queueIds: ready.map((e) => e.id).toList(),
        );
  }

  @override
  Widget build(BuildContext context) {
    final libAsync = ref.watch(ariaLibraryProvider);

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            Masthead(title: 'ARIA', actionIcon: Icons.search, onAction: () => context.push(Routes.ariaSearch)),
            Expanded(
              child: libAsync.when(
                loading: () => const ShimmerList(),
                error: (e, _) => ErrorRetry(
                  message: 'Couldn\'t load your music.',
                  onRetry: () => ref.read(ariaLibraryProvider.notifier).refresh(),
                ),
                data: (lib) {
                  if (lib.tracks.isEmpty && lib.playlists.isEmpty) {
                    return const EmptyState(
                      icon: Icons.library_music_outlined,
                      message: 'No tracks yet. ARIA is composing from your brain.',
                    );
                  }
                  return _content(lib);
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _content(AriaLibrary lib) {
    final allReady = lib.readyTracks;
    final tracks = _mood == null ? lib.tracks : lib.tracks.where((t) => t.mood == _mood).toList();
    final ready = tracks.where((t) => !t.processing).toList();
    final moodsPresent = Mood.values.where((m) => allReady.any((t) => t.mood == m)).toList();
    final s = ref.watch(ariaPlayerProvider);

    return RefreshIndicator(
      onRefresh: () => ref.read(ariaLibraryProvider.notifier).refresh(),
      child: ListView(
        children: [
          // Mood filter row.
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(16, 2, 16, 14),
            child: Row(
              children: [
                MoodChip(label: 'All', active: _mood == null, onTap: () => setState(() => _mood = null)),
                for (final m in Mood.values) ...[
                  const SizedBox(width: 8),
                  MoodChip(label: m.label, color: m.color, active: _mood == m, onTap: () => setState(() => _mood = m)),
                ],
              ],
            ),
          ),
          if (s.hasTrack) ...[
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: _NowPlayingHero(),
            ),
            const SizedBox(height: AppDimens.space2),
          ],
          if (lib.playlists.isNotEmpty) ...[
            _SectionHead('Your playlists'),
            SizedBox(
              height: 188,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: lib.playlists.length,
                separatorBuilder: (_, __) => const SizedBox(width: 12),
                itemBuilder: (_, i) => _PlaylistCard(playlist: lib.playlists[i]),
              ),
            ),
          ],
          if (tracks.isNotEmpty) ...[
            _SectionHead('New tracks'),
            SizedBox(
              height: 184,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: tracks.length,
                separatorBuilder: (_, __) => const SizedBox(width: 12),
                itemBuilder: (_, i) => _TrackCard(track: tracks[i], onTap: () => _playTrack(tracks[i], allReady)),
              ),
            ),
          ],
          if (ready.isNotEmpty) ...[
            _SectionHead('From your brain'),
            for (final t in ready.take(4))
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                child: _FromBrainCard(track: t, onTap: () => _playTrack(t, allReady)),
              ),
          ],
          for (final m in moodsPresent) ...[
            _SectionHead(m.label),
            SizedBox(
              height: 184,
              child: Builder(
                builder: (_) {
                  final list = allReady.where((t) => t.mood == m).toList();
                  return ListView.separated(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    itemCount: list.length,
                    separatorBuilder: (_, __) => const SizedBox(width: 12),
                    itemBuilder: (_, i) => _TrackCard(track: list[i], onTap: () => _playTrack(list[i], allReady)),
                  );
                },
              ),
            ),
          ],
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

class _SectionHead extends StatelessWidget {
  const _SectionHead(this.title);
  final String title;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 10),
      child: Text(title, style: AppText.display(15).copyWith(color: context.c.textPrimary)),
    );
  }
}

class _NowPlayingHero extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final s = ref.watch(ariaPlayerProvider);
    final p = ref.read(ariaPlayerProvider.notifier);
    final t = s.track!;
    return GestureDetector(
      onTap: () => context.push(Routes.ariaNow),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Color.alphaBlend(t.mood.color.withValues(alpha: c.isDark ? 0.18 : 0.08), c.backgroundSurface),
          borderRadius: BorderRadius.circular(AppDimens.cardRadius),
          border: Border.all(color: c.borderSubtle),
        ),
        child: Row(
          children: [
            AlbumArt(title: t.title, mood: t.mood, size: 56, imageUrl: t.artUrl),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Now playing', style: AppText.mono(size: 10).copyWith(color: c.textTertiary)),
                  const SizedBox(height: 2),
                  Text(t.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.md.copyWith(color: c.textPrimary)),
                  Text(t.mood.label, style: AppText.sm.copyWith(color: t.mood.color)),
                ],
              ),
            ),
            IconButton(
              icon: Icon(s.playing ? Icons.pause_circle : Icons.play_circle, size: 36, color: c.accentPrimary),
              onPressed: p.toggle,
            ),
          ],
        ),
      ),
    );
  }
}

class _TrackCard extends StatelessWidget {
  const _TrackCard({required this.track, required this.onTap});
  final Track track;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return GestureDetector(
      onTap: track.processing ? null : onTap,
      child: SizedBox(
        width: 132,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Stack(
              children: [
                AlbumArt(title: track.title, mood: track.mood, size: 132, imageUrl: track.artUrl),
                if (track.processing)
                  Positioned.fill(
                    child: Container(
                      decoration: BoxDecoration(
                        color: c.brainAmberSurface.withValues(alpha: 0.85),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const BrainPulse(size: 22),
                          const SizedBox(height: 4),
                          Text('Generating…', style: AppText.xs.copyWith(color: c.textSecondary)),
                        ],
                      ),
                    ),
                  )
                else if (track.duration.isNotEmpty)
                  Positioned(
                    right: 6,
                    bottom: 6,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                      decoration: BoxDecoration(color: Colors.black.withValues(alpha: 0.7), borderRadius: BorderRadius.circular(999)),
                      child: Text(track.duration, style: AppText.mono(size: 10).copyWith(color: Colors.white)),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(track.processing ? 'New track' : track.title,
                maxLines: 1, overflow: TextOverflow.ellipsis,
                style: AppText.sm.copyWith(color: c.textPrimary, fontWeight: FontWeight.w500)),
            Text(track.mood.label, style: AppText.xs.copyWith(color: track.mood.color)),
          ],
        ),
      ),
    );
  }
}

class _PlaylistCard extends StatelessWidget {
  const _PlaylistCard({required this.playlist});
  final Playlist playlist;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return GestureDetector(
      onTap: () => context.push('${Routes.aria}/playlist/${playlist.id}'),
      child: SizedBox(
        width: 132,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Stack(
              children: [
                AlbumArt(title: playlist.title, mood: playlist.mood, size: 132, imageUrl: playlist.artUrl),
                Positioned(
                  left: 6,
                  bottom: 6,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(color: Colors.black.withValues(alpha: 0.7), borderRadius: BorderRadius.circular(999)),
                    child: Text('${playlist.effectiveTrackCount} tracks', style: AppText.mono(size: 10).copyWith(color: Colors.white)),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(playlist.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                style: AppText.sm.copyWith(color: c.textPrimary, fontWeight: FontWeight.w500)),
            Text(playlist.mood.label, style: AppText.xs.copyWith(color: playlist.mood.color)),
          ],
        ),
      ),
    );
  }
}

class _FromBrainCard extends StatelessWidget {
  const _FromBrainCard({required this.track, required this.onTap});
  final Track track;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AppCard(
      onTap: onTap,
      accentBorderColor: c.brainAmber,
      child: Row(
        children: [
          AlbumArt(title: track.title, mood: track.mood, size: 48, imageUrl: track.artUrl),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.md.copyWith(color: c.textPrimary)),
                if (track.topicCategory.isNotEmpty)
                  Text('From: ${track.topicCategory}', maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: AppText.sm.copyWith(color: c.brainAmber)),
              ],
            ),
          ),
          if (track.duration.isNotEmpty)
            Text(track.duration, style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
        ],
      ),
    );
  }
}
