import 'json_utils.dart';

/// Processing state of a SIGNAL video (`status` column).
enum VideoStatus {
  /// Queued but not started.
  pending,

  /// Currently rendering (script → slides → TTS → ffmpeg).
  processing,

  /// Ready to play.
  ready,

  /// Generation failed.
  failed,
}

/// A SIGNAL video — `/content/videos` row joined with its creator.
class Video {
  /// Constructs a video.
  const Video({
    required this.id,
    required this.title,
    this.description,
    this.videoUrl,
    this.thumbnailUrl,
    this.durationSeconds,
    this.status = VideoStatus.pending,
    this.score = 0.5,
    this.createdAt,
    this.topicId,
    this.category,
    this.creatorName = '',
    this.creatorAvatar,
  });

  final String id;
  final String title;
  final String? description;
  final String? videoUrl;
  final String? thumbnailUrl;
  final int? durationSeconds;
  final VideoStatus status;
  final double score;
  final DateTime? createdAt;
  final String? topicId;

  /// Category for the editorial sections, derived from the user's topic
  /// clusters when the API exposes it (else null → grouped under "All").
  final String? category;
  final String creatorName;
  final String? creatorAvatar;

  /// Decodes a video row.
  factory Video.fromJson(Map<String, dynamic> json) => Video(
        id: asStr(json['id']),
        title: asStr(json['title']),
        description: asStrOrNull(json['description']),
        videoUrl: asStrOrNull(json['video_url']),
        thumbnailUrl: asStrOrNull(json['thumbnail_url']),
        durationSeconds: asInt(json['duration_seconds']),
        status: _status(asStr(json['status'], 'pending')),
        score: asDouble(json['score']) ?? 0.5,
        createdAt: asDate(json['created_at']),
        topicId: asStrOrNull(json['topic_id']),
        category: asStrOrNull(json['category'] ?? json['topic_name'] ?? json['topic']),
        creatorName: asStr(json['creator_name']),
        creatorAvatar: asStrOrNull(json['creator_avatar']),
      );

  static VideoStatus _status(String raw) {
    switch (raw.toLowerCase()) {
      case 'ready':
      case 'complete':
      case 'completed':
      case 'done':
        return VideoStatus.ready;
      case 'processing':
      case 'rendering':
      case 'running':
        return VideoStatus.processing;
      case 'failed':
      case 'error':
        return VideoStatus.failed;
      default:
        return VideoStatus.pending;
    }
  }

  /// True while the video is still being prepared.
  bool get isProcessing => status == VideoStatus.processing || status == VideoStatus.pending;

  /// True when a playable URL exists.
  bool get isPlayable => status == VideoStatus.ready && (videoUrl?.isNotEmpty ?? false);

  /// Human duration ("3:42"), or empty when unknown.
  String get durationLabel {
    final s = durationSeconds;
    if (s == null || s <= 0) return '';
    final m = s ~/ 60;
    final r = s % 60;
    return '$m:${r.toString().padLeft(2, '0')}';
  }

  /// Score as 0–100 for the badge.
  int get scorePercent => (score * 100).round();

  /// Score rendered as a 2-decimal editorial label, e.g. "0.79".
  String get scoreLabel => score.toStringAsFixed(2);
}
