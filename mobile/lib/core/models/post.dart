import 'json_utils.dart';

/// The editorial card format a post is rendered as.
enum PostFormat {
  /// Format A — has an image; the most common card.
  imagePost,

  /// Format B — text-only, tone-tinted, the body is the hero.
  textOnly,

  /// Format C — carries an external source link.
  externalSource,
}

/// A PULSE post — `/content/posts` row joined with its creator.
///
/// Columns: id, creator_id, topic_id, body, image_url, image_prompt, tone,
/// score, total_interactions, created_at + creator_name/avatar/slug/score/bio.
class Post {
  /// Constructs a post.
  const Post({
    required this.id,
    required this.body,
    this.imageUrl,
    this.tone,
    this.score = 0.5,
    this.createdAt,
    this.topicId,
    this.creatorName = '',
    this.creatorSlug = '',
    this.creatorAvatar,
    this.linkUrl,
  });

  final String id;
  final String body;
  final String? imageUrl;
  final String? tone;
  final double score;
  final DateTime? createdAt;
  final String? topicId;
  final String creatorName;
  final String creatorSlug;
  final String? creatorAvatar;

  /// An external link extracted from the body, if present (rendered as a card).
  final String? linkUrl;

  /// Decodes a post row.
  factory Post.fromJson(Map<String, dynamic> json) {
    final body = asStr(json['body']);
    return Post(
      id: asStr(json['id']),
      body: body,
      imageUrl: asStrOrNull(json['image_url']),
      tone: asStrOrNull(json['tone']),
      score: asDouble(json['score']) ?? 0.5,
      createdAt: asDate(json['created_at']),
      topicId: asStrOrNull(json['topic_id']),
      creatorName: asStr(json['creator_name']),
      creatorSlug: asStr(json['creator_slug']),
      creatorAvatar: asStrOrNull(json['creator_avatar']),
      linkUrl: _firstUrl(body),
    );
  }

  static final _urlRe = RegExp(r'https?://[^\s)]+', caseSensitive: false);

  static String? _firstUrl(String text) => _urlRe.firstMatch(text)?.group(0);

  /// Score as a 0–100 integer for the badge.
  int get scorePercent => (score * 100).round();

  /// Score rendered as a 2-decimal editorial label, e.g. "0.81".
  String get scoreLabel => score.toStringAsFixed(2);

  /// Estimated reading time in minutes (~200 wpm, min 1).
  int get readMinutes {
    final words = body.trim().split(RegExp(r'\s+')).length;
    return (words / 200).ceil().clamp(1, 99);
  }

  /// The card format chosen by content. The backend doesn't return a topic
  /// name, so the headline is derived from the body (see [headline]).
  PostFormat get format {
    if (linkUrl != null) return PostFormat.externalSource;
    if (imageUrl != null && imageUrl!.isNotEmpty) return PostFormat.imagePost;
    return PostFormat.textOnly;
  }

  /// A short headline derived from the first sentence of the body — used as the
  /// editorial topic line on Format A/C cards (the API has no topic text).
  String get headline {
    final firstSentence = body.trim().split(RegExp(r'(?<=[.!?])\s')).first.trim();
    final clean = firstSentence.replaceAll(RegExp(r'https?://\S+'), '').trim();
    if (clean.length <= 72) return clean;
    return '${clean.substring(0, 69).trimRight()}…';
  }

  /// The link host (e.g. "reweave.eu"), or null.
  String? get linkHost {
    final u = linkUrl;
    if (u == null) return null;
    return Uri.tryParse(u)?.host.replaceFirst('www.', '');
  }
}
