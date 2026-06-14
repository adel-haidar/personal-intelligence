import 'json_utils.dart';

/// A shared AI content-creator persona (`/content/creators`).
class Creator {
  /// Constructs a creator.
  const Creator({
    required this.id,
    required this.name,
    this.slug = '',
    this.avatarUrl,
    this.bio,
    this.score = 0.5,
  });

  final String id;
  final String name;
  final String slug;
  final String? avatarUrl;
  final String? bio;
  final double score;

  /// Decodes a creator row.
  factory Creator.fromJson(Map<String, dynamic> json) => Creator(
        id: asStr(json['id']),
        name: asStr(json['name']),
        slug: asStr(json['slug']),
        avatarUrl: asStrOrNull(json['avatar_url']),
        bio: asStrOrNull(json['bio']),
        score: asDouble(json['score']) ?? 0.5,
      );
}
