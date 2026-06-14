/// ARIA domain models — AI-generated music (tracks, playlists, moods).
///
/// Plain immutable classes (no freezed) mapped to the real `/api/aria` backend
/// shapes (TrackOut / PlaylistOut). The backend's `mood` is lowercase
/// (`Mood.fromApi`), `lyrics` arrives as one newline-separated string (split
/// into lines), durations are whole seconds, and album art may carry an
/// `art_url`.
library;

import 'package:flutter/material.dart';

import 'json_utils.dart';

/// The six ARIA moods — the primary discovery axis — each with its own colour.
enum Mood {
  /// Calm — #6B8CAE.
  calm('Calm', Color(0xFF6B8CAE)),

  /// Focus — #5B5BD6.
  focus('Focus', Color(0xFF5B5BD6)),

  /// Energetic — #C0392B.
  energetic('Energetic', Color(0xFFC0392B)),

  /// Melancholic — #7C3AED.
  melancholic('Melancholic', Color(0xFF7C3AED)),

  /// Uplifting — #2D7A4F.
  uplifting('Uplifting', Color(0xFF2D7A4F)),

  /// Tense — #B45309.
  tense('Tense', Color(0xFFB45309));

  const Mood(this.label, this.color);

  /// Display label.
  final String label;

  /// The mood colour (chips, art tint, ambient).
  final Color color;

  /// Parses the backend's lowercase mood string. Unknown → [Mood.calm].
  static Mood fromApi(String? raw) {
    switch ((raw ?? '').toLowerCase()) {
      case 'calm':
        return Mood.calm;
      case 'focus':
        return Mood.focus;
      case 'energetic':
        return Mood.energetic;
      case 'melancholic':
        return Mood.melancholic;
      case 'uplifting':
        return Mood.uplifting;
      case 'tense':
        return Mood.tense;
      default:
        return Mood.calm;
    }
  }
}

/// Processing state of a track (`status` column).
enum TrackStatus {
  /// Still being generated.
  generating,

  /// Ready to play.
  ready,

  /// Generation failed.
  failed,
}

TrackStatus _trackStatus(String raw) {
  switch (raw.toLowerCase()) {
    case 'ready':
    case 'complete':
    case 'completed':
    case 'done':
      return TrackStatus.ready;
    case 'failed':
    case 'error':
      return TrackStatus.failed;
    default:
      return TrackStatus.generating;
  }
}

/// An AI-generated music track (TrackOut).
class Track {
  /// Creates a track.
  const Track({
    required this.id,
    required this.title,
    required this.mood,
    this.genre = '',
    this.topicCategory = '',
    this.durationSeconds,
    this.status = TrackStatus.ready,
    this.audioUrl,
    this.waveformUrl,
    this.artUrl,
    this.lyrics,
    this.bpm,
    this.musicalKey,
    this.instruments = const [],
    this.brainTopicIds = const [],
    this.isLiked = false,
  });

  final String id;
  final String title;
  final Mood mood;
  final String genre;

  /// The brain topic category this track was generated from ("From: …").
  final String topicCategory;

  /// Duration in whole seconds (nullable on the backend).
  final int? durationSeconds;
  final TrackStatus status;

  final String? audioUrl;
  final String? waveformUrl;
  final String? artUrl;

  /// Lyrics lines (parsed from the newline-separated backend string).
  final List<String>? lyrics;

  final int? bpm;
  final String? musicalKey;
  final List<String> instruments;
  final List<String> brainTopicIds;
  final bool isLiked;

  /// Back-compat alias used by the discovery / "From your brain" UI.
  String get topic => topicCategory;

  /// True while the track is still being generated.
  bool get processing => status == TrackStatus.generating;

  /// `m:ss` duration label, or empty when unknown.
  String get duration {
    final s = durationSeconds;
    if (s == null || s <= 0) return '';
    return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
  }

  /// Duration in whole seconds for the simulated progress timer (default 210).
  int get totalSeconds => (durationSeconds != null && durationSeconds! > 0) ? durationSeconds! : 210;

  /// Decodes a TrackOut row.
  factory Track.fromJson(Map<String, dynamic> json) {
    final rawLyrics = json['lyrics'];
    List<String>? lines;
    if (rawLyrics is String && rawLyrics.trim().isNotEmpty) {
      lines = rawLyrics.split('\n').map((l) => l.trimRight()).where((l) => l.isNotEmpty).toList();
    } else if (rawLyrics is List) {
      lines = rawLyrics.map((e) => e.toString()).where((e) => e.isNotEmpty).toList();
    }
    return Track(
      id: asStr(json['id']),
      title: asStr(json['title']),
      mood: Mood.fromApi(asStrOrNull(json['mood'])),
      genre: asStr(json['genre']),
      topicCategory: asStr(json['topic_category']),
      durationSeconds: asInt(json['duration_seconds']),
      status: _trackStatus(asStr(json['status'], 'ready')),
      audioUrl: asStrOrNull(json['audio_url']),
      waveformUrl: asStrOrNull(json['waveform_url']),
      artUrl: asStrOrNull(json['art_url']),
      lyrics: lines,
      bpm: asInt(json['bpm']),
      musicalKey: asStrOrNull(json['musical_key']),
      instruments: asStrList(json['instruments']),
      brainTopicIds: asStrList(json['brain_topic_ids']),
      isLiked: asBool(json['is_liked']),
    );
  }
}

/// A curated playlist of tracks, anchored to a mood (PlaylistOut).
class Playlist {
  /// Creates a playlist.
  const Playlist({
    required this.id,
    required this.title,
    required this.mood,
    this.artUrl,
    this.trackCount = 0,
    this.totalDurationSeconds = 0,
    this.isAutoGenerated = false,
    this.tracks = const [],
  });

  final String id;
  final String title;

  /// Resolved from `dominant_mood` (lowercase) → [Mood].
  final Mood mood;
  final String? artUrl;

  final int trackCount;

  /// Total duration in whole seconds.
  final int totalDurationSeconds;
  final bool isAutoGenerated;

  /// Member tracks (present only on the detail endpoint).
  final List<Track> tracks;

  /// Back-compat alias for the UI (was `name`).
  String get name => title;

  /// Effective track count (loaded list takes precedence).
  int get effectiveTrackCount => tracks.isNotEmpty ? tracks.length : trackCount;

  /// "1h 4m" / "24m" total-duration label.
  String get totalLabel {
    final secs = totalDurationSeconds;
    final h = secs ~/ 3600;
    final m = (secs % 3600) ~/ 60;
    return h > 0 ? '${h}h ${m}m' : '${m}m';
  }

  /// Decodes a PlaylistOut row (tracks attached when present).
  factory Playlist.fromJson(Map<String, dynamic> json) {
    final rawTracks = json['tracks'];
    return Playlist(
      id: asStr(json['id']),
      title: asStr(json['title']),
      mood: Mood.fromApi(asStrOrNull(json['dominant_mood'])),
      artUrl: asStrOrNull(json['art_url']),
      trackCount: asInt(json['track_count']) ?? 0,
      totalDurationSeconds: asInt(json['total_duration']) ?? 0,
      isAutoGenerated: asBool(json['is_auto_generated']),
      tracks: rawTracks is List
          ? rawTracks.whereType<Map>().map((e) => Track.fromJson(Map<String, dynamic>.from(e))).toList()
          : const [],
    );
  }
}

/// The ARIA library response (`GET /api/aria/library`).
class AriaLibrary {
  /// Creates a library snapshot.
  const AriaLibrary({
    this.tracks = const [],
    this.playlists = const [],
    this.likedCount = 0,
    this.totalTracks = 0,
  });

  final List<Track> tracks;
  final List<Playlist> playlists;
  final int likedCount;
  final int totalTracks;

  /// Tracks that are fully generated (not processing).
  List<Track> get readyTracks => tracks.where((t) => !t.processing).toList();

  /// Resolves a track by id, or null.
  Track? trackById(String id) {
    for (final t in tracks) {
      if (t.id == id) return t;
    }
    return null;
  }

  /// Decodes the library response.
  factory AriaLibrary.fromJson(Map<String, dynamic> json) {
    List<T> list<T>(Object? v, T Function(Map<String, dynamic>) fromJson) =>
        v is List ? v.whereType<Map>().map((e) => fromJson(Map<String, dynamic>.from(e))).toList() : <T>[];
    return AriaLibrary(
      tracks: list(json['tracks'], Track.fromJson),
      playlists: list(json['playlists'], Playlist.fromJson),
      likedCount: asInt(json['liked_count']) ?? 0,
      totalTracks: asInt(json['total_tracks']) ?? 0,
    );
  }
}
