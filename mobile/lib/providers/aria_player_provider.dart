import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../core/api/api_client.dart';
import '../core/api/api_endpoints.dart';
import '../core/models/music.dart';
import 'core_providers.dart';

/// Data operations for ARIA.
class AriaRepository {
  /// Creates the repository.
  AriaRepository(this._api);
  final ApiClient _api;

  /// `GET /api/aria/library` → the full library.
  Future<AriaLibrary> fetchLibrary() async {
    final data = await _api.get(ApiEndpoints.ariaLibrary);
    return AriaLibrary.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// `GET /api/aria/tracks/{id}` → a single track.
  Future<Track> fetchTrack(String id) async {
    final data = await _api.get(ApiEndpoints.ariaTrack(id));
    return Track.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// `GET /api/aria/playlists/{id}` → a playlist with its tracks.
  Future<Playlist> fetchPlaylist(String id) async {
    final data = await _api.get(ApiEndpoints.ariaPlaylist(id));
    return Playlist.fromJson(Map<String, dynamic>.from(data as Map));
  }

  /// `GET /api/aria/search?q=` → `{query, tracks}`.
  Future<List<Track>> search(String q) async {
    final data = await _api.get(ApiEndpoints.ariaSearch, query: {'q': q});
    final map = Map<String, dynamic>.from(data as Map);
    final list = map['tracks'] is List ? map['tracks'] as List : const [];
    return list.whereType<Map>().map((e) => Track.fromJson(Map<String, dynamic>.from(e))).toList();
  }

  /// `POST /api/aria/play` → `{play_id, track}`.
  Future<String?> play(String trackId, {String? playId}) async {
    final data = await _api.post(ApiEndpoints.ariaPlay, body: {
      'track_id': trackId,
      if (playId != null) 'play_id': playId,
    });
    if (data is Map && data['play_id'] != null) return data['play_id'].toString();
    return null;
  }

  /// `POST /api/aria/play-end` — logs a finished/abandoned play.
  Future<void> playEnd(String playId, int playDurationSeconds) =>
      _api.post(ApiEndpoints.ariaPlayEnd, body: {
        'play_id': playId,
        'play_duration_seconds': playDurationSeconds,
      });

  /// `POST /api/aria/like` — toggles a like.
  Future<void> like(String trackId, bool liked) =>
      _api.post(ApiEndpoints.ariaLike, body: {'track_id': trackId, 'liked': liked});
}

/// ARIA data repository.
final ariaRepositoryProvider = Provider<AriaRepository>((ref) => AriaRepository(ref.watch(apiClientProvider)));

/// The ARIA library — `GET /api/aria/library`. Polls while anything generates,
/// and seeds the player's liked set from `is_liked`.
class AriaLibraryController extends AsyncNotifier<AriaLibrary> {
  Timer? _poll;

  @override
  Future<AriaLibrary> build() async {
    ref.onDispose(() => _poll?.cancel());
    final lib = await ref.read(ariaRepositoryProvider).fetchLibrary();
    _afterLoad(lib);
    return lib;
  }

  /// Pull-to-refresh.
  Future<void> refresh() async {
    state = await AsyncValue.guard(() async {
      final lib = await ref.read(ariaRepositoryProvider).fetchLibrary();
      _afterLoad(lib);
      return lib;
    });
  }

  void _afterLoad(AriaLibrary lib) {
    // Seed the player's liked set + known catalog (for queue/next resolution).
    ref.read(ariaPlayerProvider.notifier).seedFromLibrary(lib);
    final anyProcessing = lib.tracks.any((t) => t.processing);
    if (anyProcessing) {
      _poll ??= Timer.periodic(const Duration(seconds: 15), (_) => _tick());
    } else {
      _poll?.cancel();
      _poll = null;
    }
  }

  Future<void> _tick() async {
    try {
      final lib = await ref.read(ariaRepositoryProvider).fetchLibrary();
      state = AsyncData(lib);
      _afterLoad(lib);
    } catch (_) {/* keep last good state; retry next tick */}
  }
}

/// ARIA library provider.
final ariaLibraryProvider =
    AsyncNotifierProvider<AriaLibraryController, AriaLibrary>(AriaLibraryController.new);

/// A single playlist by id (with its tracks).
final playlistDetailProvider =
    FutureProvider.family<Playlist, String>((ref, id) => ref.watch(ariaRepositoryProvider).fetchPlaylist(id));

/// ARIA search results for a query.
final ariaSearchProvider =
    FutureProvider.family<List<Track>, String>((ref, q) => ref.watch(ariaRepositoryProvider).search(q));

/// App-level ARIA player state. The single source of truth for continuous
/// playback that survives navigation — the mini-player and Now Playing both
/// read from here. Mounted above the router so it is never disposed mid-session.
class AriaPlayerState {
  /// Creates the player state.
  const AriaPlayerState({
    this.track,
    this.playing = false,
    this.progress = 0,
    this.queue = const [],
    this.liked = const {},
    this.shuffle = false,
    this.repeat = false,
    this.volume = 0.8,
    this.dismissed = false,
  });

  /// The current track, or null if nothing has been played this session.
  final Track? track;
  final bool playing;

  /// 0–100 progress through the current track.
  final double progress;

  /// Upcoming track ids.
  final List<String> queue;

  /// Liked track ids.
  final Set<String> liked;
  final bool shuffle;
  final bool repeat;

  /// 0–1 volume.
  final double volume;

  /// Whether the mini-player has been swiped away this session.
  final bool dismissed;

  /// Whether a track has been started (mini-player visibility gate).
  bool get hasTrack => track != null;

  /// Whether [id] is liked.
  bool isLiked(String id) => liked.contains(id);

  AriaPlayerState copyWith({
    Track? track,
    bool? playing,
    double? progress,
    List<String>? queue,
    Set<String>? liked,
    bool? shuffle,
    bool? repeat,
    double? volume,
    bool? dismissed,
  }) {
    return AriaPlayerState(
      track: track ?? this.track,
      playing: playing ?? this.playing,
      progress: progress ?? this.progress,
      queue: queue ?? this.queue,
      liked: liked ?? this.liked,
      shuffle: shuffle ?? this.shuffle,
      repeat: repeat ?? this.repeat,
      volume: volume ?? this.volume,
      dismissed: dismissed ?? this.dismissed,
    );
  }
}

/// Drives [AriaPlayerState] using a real audio engine.
///
/// The engine is `video_player` (it plays audio-only streams too): the track's
/// `audio_url` is loaded into a [VideoPlayerController] and its position drives
/// [progress]. Tracks without an `audio_url` (still generating) fall back to a
/// simulated 500ms timer. `/play` + `/play-end` are logged to the API.
class AriaPlayerController extends Notifier<AriaPlayerState> {
  Timer? _tick;

  /// The real audio engine for the current track (null while using the timer
  /// fallback or before anything has played).
  VideoPlayerController? _engine;
  bool get _engineActive => _engine != null && _engine!.value.isInitialized;

  /// Guards the completion handler from firing twice (the listener keeps ticking
  /// until the controller is replaced on the next microtask).
  bool _completing = false;

  /// The loaded catalog, kept in memory for queue/next resolution.
  final Map<String, Track> _catalog = {};
  List<Track> _ready = const [];

  /// The current backend play session id (from `/play`).
  String? _playId;

  /// Wall-clock progress (seconds) used when reporting `/play-end`.
  int _elapsedSeconds = 0;

  @override
  AriaPlayerState build() {
    ref.onDispose(() {
      _tick?.cancel();
      _disposeEngine();
    });
    return const AriaPlayerState();
  }

  /// Seeds the liked set and the in-memory catalog from the loaded library.
  /// Liked ids the user has toggled this session are preserved.
  void seedFromLibrary(AriaLibrary lib) {
    _catalog
      ..clear()
      ..addEntries(lib.tracks.map((t) => MapEntry(t.id, t)));
    _ready = lib.readyTracks;
    final seeded = <String>{
      for (final t in lib.tracks)
        if (t.isLiked) t.id,
    };
    // Merge server-liked with any session toggles already present.
    state = state.copyWith(liked: {...seeded, ...state.liked});
  }

  Track? _trackById(String id) => _catalog[id];

  /// Starts [track]; optionally replaces the queue with [queueIds]. Logs `/play`.
  void playTrack(Track track, {List<String>? queueIds}) {
    if (track.processing) return;
    _reportPlayEnd();
    state = state.copyWith(
      track: track,
      progress: 0,
      playing: true,
      dismissed: false,
      queue: queueIds == null ? state.queue : queueIds.where((id) => id != track.id).toList(),
    );
    _elapsedSeconds = 0;
    _playId = null;
    _logPlay(track.id);
    _engage(track);
  }

  /// Loads [track] into the audio engine and starts it. Falls back to the
  /// simulated timer when the track has no playable `audio_url`.
  void _engage(Track track) {
    _tick?.cancel();
    _disposeEngine();
    final url = track.audioUrl;
    if (url == null || url.isEmpty) {
      _restartTimer(); // still-generating track: simulate.
      return;
    }
    _completing = false;
    final engine = VideoPlayerController.networkUrl(Uri.parse(url));
    _engine = engine;
    engine.initialize().then((_) {
      // A newer track may have superseded this one mid-initialize.
      if (_engine != engine) {
        engine.dispose();
        return;
      }
      engine.setVolume(state.volume);
      engine.addListener(_engineListener);
      if (state.playing) engine.play();
    }).catchError((_) {
      // Engine failed (bad URL/codec) — degrade to the simulated timer.
      if (_engine == engine) {
        _disposeEngine();
        _restartTimer();
      }
    });
  }

  void _engineListener() {
    final engine = _engine;
    if (engine == null || !engine.value.isInitialized) return;
    final total = engine.value.duration.inMilliseconds;
    if (total <= 0) return;
    final pos = engine.value.position.inMilliseconds;
    _elapsedSeconds = (pos / 1000).round();
    final pct = (pos / total * 100).clamp(0, 100).toDouble();
    if (pct >= 99.5 || (!engine.value.isPlaying && pos >= total)) {
      if (_completing) return;
      _completing = true;
      _reportPlayEnd();
      if (state.repeat) {
        _completing = false;
        engine.seekTo(Duration.zero);
        engine.play();
        state = state.copyWith(progress: 0);
      } else {
        // Defer: `next()` replaces/disposes this controller — don't do it from
        // inside its own listener callback.
        scheduleMicrotask(next);
      }
      return;
    }
    if ((pct - state.progress).abs() >= 0.2) state = state.copyWith(progress: pct);
  }

  void _disposeEngine() {
    final e = _engine;
    _engine = null;
    if (e != null) {
      e.removeListener(_engineListener);
      e.dispose();
    }
  }

  Future<void> _logPlay(String trackId) async {
    try {
      _playId = await ref.read(ariaRepositoryProvider).play(trackId);
    } catch (_) {/* non-fatal — playback is local */}
  }

  void _reportPlayEnd() {
    final id = _playId;
    if (id == null) return;
    final secs = _elapsedSeconds;
    _playId = null;
    unawaited(_safePlayEnd(id, secs));
  }

  Future<void> _safePlayEnd(String playId, int secs) async {
    try {
      await ref.read(ariaRepositoryProvider).playEnd(playId, secs);
    } catch (_) {/* non-fatal */}
  }

  /// Toggles play/pause for the current track.
  void toggle() {
    if (state.track == null) return;
    final nowPlaying = !state.playing;
    state = state.copyWith(playing: nowPlaying);
    if (_engineActive) {
      nowPlaying ? _engine!.play() : _engine!.pause();
    } else {
      _restartTimer();
    }
  }

  /// Advances to the next track — from the queue if present, else the next ready
  /// catalog track (wrapping).
  void next() {
    if (state.queue.isNotEmpty) {
      final head = state.queue.first;
      final rest = state.queue.sublist(1);
      final t = _trackById(head);
      if (t != null) {
        playTrack(t, queueIds: null);
        state = state.copyWith(queue: rest);
        return;
      }
      state = state.copyWith(queue: rest);
    }
    if (_ready.isEmpty) return;
    final i = state.track == null ? -1 : _ready.indexWhere((t) => t.id == state.track!.id);
    final t = _ready[(i + 1) % _ready.length];
    playTrack(t);
  }

  /// Restarts the current track (the player's "previous" affordance).
  void prev() {
    if (state.track == null) return;
    state = state.copyWith(progress: 0, playing: true);
    _elapsedSeconds = 0;
    if (_engineActive) {
      _engine!.seekTo(Duration.zero);
      _engine!.play();
    } else {
      _restartTimer();
    }
  }

  /// Seeks to a 0–100 [percent] position.
  void seek(double percent) {
    final p = percent.clamp(0, 100).toDouble();
    state = state.copyWith(progress: p);
    final total = state.track?.totalSeconds ?? 0;
    _elapsedSeconds = (total * p / 100).round();
    if (_engineActive) {
      final dur = _engine!.value.duration;
      _engine!.seekTo(dur * (p / 100));
    }
  }

  /// Toggles like for [id] and persists it to the backend.
  void toggleLike(String id) {
    final next = Set<String>.from(state.liked);
    final nowLiked = !next.contains(id);
    if (nowLiked) {
      next.add(id);
    } else {
      next.remove(id);
    }
    state = state.copyWith(liked: next);
    unawaited(_safeLike(id, nowLiked));
  }

  Future<void> _safeLike(String id, bool liked) async {
    try {
      await ref.read(ariaRepositoryProvider).like(id, liked);
    } catch (_) {/* non-fatal — local state already updated */}
  }

  /// Appends [id] to the queue.
  void enqueue(String id) => state = state.copyWith(queue: [...state.queue, id]);

  /// Removes the queue item at [index].
  void dequeue(int index) {
    if (index < 0 || index >= state.queue.length) return;
    final q = List<String>.from(state.queue)..removeAt(index);
    state = state.copyWith(queue: q);
  }

  /// Replaces the whole queue.
  void setQueue(List<String> ids) => state = state.copyWith(queue: ids);

  /// Clears the queue.
  void clearQueue() => state = state.copyWith(queue: const []);

  /// Resolves a queued track id to a [Track] (for the queue sheet).
  Track? trackForId(String id) => _trackById(id);

  /// Reorders the queue (drag-to-reorder).
  void reorderQueue(int oldIndex, int newIndex) {
    final q = List<String>.from(state.queue);
    if (oldIndex < 0 || oldIndex >= q.length) return;
    var target = newIndex;
    if (target > oldIndex) target -= 1;
    target = target.clamp(0, q.length - 1);
    final item = q.removeAt(oldIndex);
    q.insert(target, item);
    state = state.copyWith(queue: q);
  }

  /// Toggles shuffle.
  void toggleShuffle() => state = state.copyWith(shuffle: !state.shuffle);

  /// Toggles repeat.
  void toggleRepeat() => state = state.copyWith(repeat: !state.repeat);

  /// Sets the volume (0–1).
  void setVolume(double v) {
    final vol = v.clamp(0, 1).toDouble();
    state = state.copyWith(volume: vol);
    if (_engineActive) _engine!.setVolume(vol);
  }

  /// Dismisses the mini-player (swipe down) — pauses and hides.
  void dismiss() {
    _tick?.cancel();
    if (_engineActive) _engine!.pause();
    _reportPlayEnd();
    state = state.copyWith(playing: false, dismissed: true);
  }

  void _restartTimer() {
    _tick?.cancel();
    final track = state.track;
    if (track == null || !state.playing) return;
    final total = track.totalSeconds;
    _tick = Timer.periodic(const Duration(milliseconds: 500), (_) {
      _elapsedSeconds = (total * state.progress / 100).round();
      final step = (100 / total) * 0.5; // 0.5s of progress per tick
      final np = state.progress + step;
      if (np >= 100) {
        _reportPlayEnd();
        if (state.repeat) {
          state = state.copyWith(progress: 0);
          _elapsedSeconds = 0;
        } else {
          next();
        }
        return;
      }
      state = state.copyWith(progress: np);
    });
  }
}

/// The app-wide ARIA player provider.
final ariaPlayerProvider =
    NotifierProvider<AriaPlayerController, AriaPlayerState>(AriaPlayerController.new);
