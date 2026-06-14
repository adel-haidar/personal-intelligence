import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:video_player/video_player.dart';

import '../../core/models/story.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/brain_pulse.dart';
import '../../core/widgets/states.dart';
import '../../providers/stories_provider.dart';
import 'stories_widgets.dart';

String _fmt(int total) {
  final s = total < 0 ? 0 : total;
  return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
}

/// The immersive STORIES player. Plays a film (`?film=`), a series episode
/// (`?series=&ep=`), or a continue-watching episode (`?episode=`). Controls
/// auto-hide after 3s; −10/play/+10; amber scrubber; next-episode prompt; end
/// screen.
///
/// Plays the real `video_url` via [VideoPlayerController]; content still
/// generating (no URL) falls back to a simulated progress timer. Watch progress
/// is posted to `/api/stories/progress` on dispose.
class StoriesPlayerScreen extends ConsumerStatefulWidget {
  /// Creates the player. One of [filmId], [seriesId]+[episodeNumber], [episodeId].
  const StoriesPlayerScreen({super.key, this.filmId, this.seriesId, this.episodeNumber, this.episodeId});

  final String? filmId;
  final String? seriesId;
  final int? episodeNumber;

  /// A continue-watching episode id (no series context available).
  final String? episodeId;

  @override
  ConsumerState<StoriesPlayerScreen> createState() => _StoriesPlayerScreenState();
}

class _StoriesPlayerScreenState extends ConsumerState<StoriesPlayerScreen> {
  Film? _film;
  Series? _series;
  Episode? _episode;
  bool _resolved = false;
  bool _failed = false;

  bool _controls = true;
  bool _playing = true;
  double _progress = 6; // 0–100
  bool _showNext = false;
  bool _ended = false;
  Timer? _hideTimer;
  Timer? _tick;

  /// Real video engine for the current film/episode `video_url` (null while the
  /// content has no playable URL — then the simulated [_tick] drives progress).
  VideoPlayerController? _video;
  bool get _videoActive => _video != null && _video!.value.isInitialized;

  /// The current playable URL (film or current episode).
  String? get _videoUrl => _isSeries ? _ep?.videoUrl : _film?.videoUrl;

  @override
  void initState() {
    super.initState();
    _poke();
    WidgetsBinding.instance.addPostFrameCallback((_) => _resolve());
  }

  Future<void> _resolve() async {
    final repo = ref.read(storiesRepositoryProvider);
    try {
      if (widget.seriesId != null) {
        final s = await repo.fetchSeries(widget.seriesId!);
        Episode? ep;
        for (final e in s.episodes) {
          if (e.number == (widget.episodeNumber ?? 1)) {
            ep = e;
            break;
          }
        }
        ep ??= s.episodes.isNotEmpty ? s.episodes.first : null;
        if (!mounted) return;
        setState(() {
          _series = s;
          _episode = ep;
          _resolved = true;
        });
      } else if (widget.episodeId != null) {
        // Continue-watching episode: we have only the episode id. Fetch the
        // library and locate the owning series so transport/next work.
        final lib = await ref.read(storiesLibraryProvider.future);
        Series? owner;
        Episode? ep;
        for (final s in lib.series) {
          final eps = await repo.fetchEpisodes(s.id);
          for (final e in eps) {
            if (e.id == widget.episodeId) {
              owner = s.withEpisodes(eps);
              ep = e;
              break;
            }
          }
          if (ep != null) break;
        }
        if (!mounted) return;
        setState(() {
          _series = owner;
          _episode = ep;
          _resolved = true;
          _failed = ep == null;
        });
      } else if (widget.filmId != null) {
        final f = await repo.fetchFilm(widget.filmId!);
        if (!mounted) return;
        setState(() {
          _film = f;
          _progress = (f.watchProgress?.percent ?? 6).toDouble();
          _resolved = true;
        });
      } else {
        setState(() {
          _resolved = true;
          _failed = true;
        });
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _resolved = true;
        _failed = true;
      });
    }
    if (mounted && !_failed) _engage();
  }

  Series? get _s => _series;
  Episode? get _ep => _episode;
  bool get _isSeries => _s != null && _ep != null;

  String get _title => _isSeries ? '${_s!.title} — ${_ep!.title}' : (_film?.title ?? '');
  int get _totalSeconds {
    final d = _isSeries ? _ep!.durationSeconds : _film?.durationSeconds;
    return (d == null || d <= 0) ? 0 : d.round();
  }

  String get _durationLabel => _isSeries ? _ep!.duration : (_film?.duration ?? '0:00');

  Episode? get _nextEp {
    if (!_isSeries) return null;
    for (final e in _s!.episodes) {
      if (e.number == _ep!.number + 1 && e.seasonNumber == _ep!.seasonNumber) return e;
    }
    return null;
  }

  void _poke() {
    _hideTimer?.cancel();
    if (!_controls) setState(() => _controls = true);
    _hideTimer = Timer(const Duration(seconds: 3), () {
      if (mounted) setState(() => _controls = false);
    });
  }

  void _restartTick() {
    _tick?.cancel();
    if (!_playing) return;
    final total = _totalSeconds;
    if (total <= 0) return;
    _tick = Timer.periodic(const Duration(milliseconds: 500), (_) {
      if (!mounted) return;
      setState(() {
        _progress = (_progress + (100 / total) * 0.5).clamp(0, 100);
        if (_nextEp != null && _progress >= 88 && !_showNext && !_ended) _showNext = true;
        if (_progress >= 100) {
          _ended = true;
          _showNext = false;
          _playing = false;
          _tick?.cancel();
        }
      });
    });
  }

  /// Loads the current content into the video engine; falls back to the
  /// simulated timer when there is no playable `video_url`.
  void _engage() {
    _tick?.cancel();
    _disposeVideo();
    final url = _videoUrl;
    if (url == null || url.isEmpty) {
      _restartTick();
      return;
    }
    final v = VideoPlayerController.networkUrl(Uri.parse(url));
    _video = v;
    v.initialize().then((_) {
      if (!mounted || _video != v) {
        v.dispose();
        return;
      }
      final total = v.value.duration.inMilliseconds;
      if (total > 0 && _progress > 0) {
        v.seekTo(Duration(milliseconds: (total * _progress / 100).round()));
      }
      if (_playing) v.play();
      v.addListener(_videoListener);
      setState(() {});
    }).catchError((_) {
      if (_video == v) {
        _disposeVideo();
        if (mounted) _restartTick();
      }
    });
  }

  void _videoListener() {
    final v = _video;
    if (v == null || !v.value.isInitialized || !mounted) return;
    final total = v.value.duration.inMilliseconds;
    if (total <= 0) return;
    final pos = v.value.position.inMilliseconds;
    final pct = (pos / total * 100).clamp(0, 100).toDouble();
    final completed = !v.value.isPlaying && pos >= total;
    setState(() {
      _progress = pct;
      if (_nextEp != null && pct >= 88 && !_showNext && !_ended) _showNext = true;
      if (pct >= 99.5 || completed) {
        _ended = true;
        _showNext = false;
        _playing = false;
      }
    });
  }

  void _disposeVideo() {
    final v = _video;
    _video = null;
    if (v != null) {
      v.removeListener(_videoListener);
      v.dispose();
    }
  }

  void _seekToPct(double pct) {
    final np = pct.clamp(0, 100).toDouble();
    setState(() => _progress = np);
    if (_videoActive) {
      _video!.seekTo(_video!.value.duration * (np / 100));
    }
    _poke();
  }

  void _togglePlay() {
    setState(() => _playing = !_playing);
    if (_videoActive) {
      _playing ? _video!.play() : _video!.pause();
    } else {
      _restartTick();
    }
    _poke();
  }

  void _skip(double delta) => _seekToPct(_progress + delta);

  void _playEpisode(int number) {
    Episode? target;
    for (final e in _s!.episodes) {
      if (e.number == number) {
        target = e;
        break;
      }
    }
    target ??= _s!.episodes.isNotEmpty ? _s!.episodes.first : null;
    if (target == null) return;
    setState(() {
      _episode = target;
      _progress = 4;
      _ended = false;
      _showNext = false;
      _playing = true;
    });
    _engage();
    _poke();
  }

  void _postProgress() {
    final total = _totalSeconds;
    if (total <= 0) return;
    final pos = (total * _progress / 100).round();
    if (pos <= 0) return;
    final repo = ref.read(storiesRepositoryProvider);
    if (_isSeries) {
      repo.postProgress(
        contentType: 'episode',
        contentId: _ep!.id,
        positionSeconds: pos,
        durationSeconds: total,
      );
    } else if (_film != null) {
      repo.postProgress(
        contentType: 'film',
        contentId: _film!.id,
        positionSeconds: pos,
        durationSeconds: total,
      );
    }
  }

  @override
  void dispose() {
    _postProgress();
    _hideTimer?.cancel();
    _tick?.cancel();
    _disposeVideo();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_resolved) {
      return const Scaffold(backgroundColor: Colors.black, body: Center(child: BrainPulse(size: 28)));
    }
    if (_failed || (_film == null && !_isSeries)) {
      return const Scaffold(backgroundColor: Colors.black, body: EmptyState(message: 'This isn\'t available right now.'));
    }
    final total = _totalSeconds;
    final curSec = (total * _progress / 100).round();
    final leftSec = total - curSec;
    final posterUrl = _isSeries ? (_ep!.thumbnailUrl) : (_film?.posterUrl ?? _film?.thumbnailUrl);

    return Scaffold(
      backgroundColor: Colors.black,
      body: GestureDetector(
        onTap: _poke,
        child: Stack(
          fit: StackFit.expand,
          children: [
            // Video surface — the real frame when the engine is ready, else
            // the key-visual poster.
            if (_videoActive)
              Center(
                child: AspectRatio(
                  aspectRatio: _video!.value.aspectRatio == 0 ? 16 / 9 : _video!.value.aspectRatio,
                  child: VideoPlayer(_video!),
                ),
              )
            else ...[
              DecoratedBox(decoration: posterDecoration(_title)),
              posterHighlight(_title),
              Positioned.fill(child: PosterImage(url: posterUrl)),
            ],
            // Scrim for control legibility (kept light over live video).
            if (!_videoActive || _controls)
              ColoredBox(color: Colors.black.withValues(alpha: _videoActive ? 0.25 : 0.35)),

            if (_controls && !_ended) ..._buildControls(curSec, leftSec),
            if (_showNext && _nextEp != null && !_ended) _buildNextPrompt(),
            if (_ended) _buildEndScreen(),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildControls(int curSec, int leftSec) {
    return [
      // Top scrim.
      const Positioned(
        top: 0,
        left: 0,
        right: 0,
        height: 110,
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [Color(0x80000000), Colors.transparent]),
          ),
        ),
      ),
      Positioned(
        top: MediaQuery.of(context).padding.top + 4,
        left: 4,
        right: 12,
        child: Row(
          children: [
            IconButton(icon: const Icon(Icons.arrow_back, color: Colors.white), onPressed: () => context.pop()),
            Expanded(
              child: Text(_title,
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.display(14).copyWith(color: Colors.white, fontWeight: FontWeight.w500)),
            ),
            const SizedBox(width: 8),
            Icon(Icons.cast, size: 18, color: Colors.white.withValues(alpha: 0.5)),
          ],
        ),
      ),
      // Center transport.
      Positioned.fill(
        child: Center(
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              IconButton(
                icon: const Icon(Icons.replay_10, color: Colors.white, size: 32),
                onPressed: () => _skip(-7),
              ),
              const SizedBox(width: 24),
              GestureDetector(
                onTap: _togglePlay,
                child: Container(
                  width: 64,
                  height: 64,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.22),
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white.withValues(alpha: 0.3)),
                  ),
                  child: Icon(_playing ? Icons.pause : Icons.play_arrow_rounded, color: Colors.white, size: 32),
                ),
              ),
              const SizedBox(width: 24),
              IconButton(
                icon: const Icon(Icons.forward_10, color: Colors.white, size: 32),
                onPressed: () => _skip(7),
              ),
            ],
          ),
        ),
      ),
      // Bottom scrim + scrubber.
      const Positioned(
        bottom: 0,
        left: 0,
        right: 0,
        height: 140,
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(begin: Alignment.bottomCenter, end: Alignment.topCenter, colors: [Color(0xB3000000), Colors.transparent]),
          ),
        ),
      ),
      Positioned(
        left: 16,
        right: 16,
        bottom: MediaQuery.of(context).padding.bottom + 24,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _Scrubber(
              progress: _progress,
              onSeek: _seekToPct,
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('${_fmt(curSec)} / $_durationLabel', style: AppText.mono(size: 12).copyWith(color: Colors.white)),
                Row(
                  children: [
                    Text('1080p', style: AppText.mono(size: 10).copyWith(color: Colors.white.withValues(alpha: 0.4))),
                    const SizedBox(width: 16),
                    Icon(Icons.volume_up_outlined, size: 16, color: Colors.white),
                    const SizedBox(width: 16),
                    Icon(Icons.fullscreen, size: 16, color: Colors.white),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 2),
            Align(
              alignment: Alignment.centerRight,
              child: Text('${_fmt(leftSec)} left', style: AppText.mono(size: 11).copyWith(color: Colors.white.withValues(alpha: 0.6))),
            ),
          ],
        ),
      ),
    ];
  }

  Widget _buildNextPrompt() {
    final c = context.c;
    final next = _nextEp!;
    return Positioned(
      right: 16,
      bottom: MediaQuery.of(context).padding.bottom + 90,
      child: Container(
        width: 240,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: c.backgroundSurface.withValues(alpha: 0.92),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: c.borderMedium),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Up next in 0:30', style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
            const SizedBox(height: 4),
            Text('S${next.seasonNumber}E${next.number} · ${next.title}', style: AppText.md.copyWith(color: c.textPrimary, fontSize: 14)),
            if (next.duration.isNotEmpty) ...[
              const SizedBox(height: 2),
              Text(next.duration, style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
            ],
            const SizedBox(height: 10),
            ClipRRect(
              borderRadius: BorderRadius.circular(2),
              child: SizedBox(
                height: 3,
                child: Stack(children: [
                  Positioned.fill(child: ColoredBox(color: c.borderMedium)),
                  FractionallySizedBox(widthFactor: 0.4, child: ColoredBox(color: c.brainAmber)),
                ]),
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: AppButton(label: 'Play now', expand: true, onPressed: () => _playEpisode(next.number)),
                ),
                const SizedBox(width: 8),
                AppButton(label: 'Cancel', variant: AppButtonVariant.outlined, onPressed: () => setState(() => _showNext = false)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEndScreen() {
    final next = _nextEp;
    final related = _film?.related.where((f) => !f.processing).take(3).toList() ?? const [];
    return Positioned.fill(
      child: ColoredBox(
        color: Colors.black.withValues(alpha: 0.78),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (next != null)
                AppButton(label: 'Play next', icon: Icons.play_arrow_rounded, onPressed: () => _playEpisode(next.number))
              else
                AppButton(label: 'Back to Stories', variant: AppButtonVariant.outlined, onPressed: () => context.pop()),
              const SizedBox(height: 12),
              Text(_title, textAlign: TextAlign.center, style: AppText.sm.copyWith(color: Colors.white.withValues(alpha: 0.7))),
              if (related.isNotEmpty) ...[
                const SizedBox(height: 28),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text('More like this', style: AppText.label.copyWith(color: Colors.white.withValues(alpha: 0.5), letterSpacing: 0.6)),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  height: 144,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    children: [
                      for (final f in related)
                        Padding(
                          padding: const EdgeInsets.only(right: 12),
                          child: SizedBox(
                            width: 96,
                            child: GestureDetector(
                              onTap: () {
                                context.pop();
                                context.push('${Routes.stories}/film/${f.id}');
                              },
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(8),
                                child: AspectRatio(
                                  aspectRatio: 2 / 3,
                                  child: Stack(
                                    fit: StackFit.expand,
                                    children: [
                                      DecoratedBox(decoration: posterDecoration(f.title)),
                                      posterHighlight(f.title),
                                      Positioned.fill(child: PosterImage(url: f.posterUrl ?? f.thumbnailUrl)),
                                      const DecoratedBox(decoration: BoxDecoration(gradient: cinematicScrim)),
                                      Positioned(
                                        left: 8,
                                        right: 8,
                                        bottom: 10,
                                        child: Text(f.title,
                                            maxLines: 2, overflow: TextOverflow.ellipsis, style: AppText.display(11).copyWith(color: Colors.white)),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// A seekable amber scrubber with a white thumb.
class _Scrubber extends StatelessWidget {
  const _Scrubber({required this.progress, required this.onSeek});
  final double progress;
  final ValueChanged<double> onSeek;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        void handle(Offset local) => onSeek((local.dx / width * 100).clamp(0, 100));
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapDown: (d) => handle(d.localPosition),
          onHorizontalDragUpdate: (d) => handle(d.localPosition),
          child: SizedBox(
            height: 16,
            child: Stack(
              alignment: Alignment.centerLeft,
              children: [
                Container(height: 4, decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.25), borderRadius: BorderRadius.circular(2))),
                FractionallySizedBox(
                  widthFactor: (progress / 100).clamp(0.0, 1.0),
                  child: Container(height: 4, decoration: BoxDecoration(color: c.brainAmber, borderRadius: BorderRadius.circular(2))),
                ),
                Align(
                  alignment: Alignment((progress / 100).clamp(0.0, 1.0) * 2 - 1, 0),
                  child: Container(width: 12, height: 12, decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle)),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
