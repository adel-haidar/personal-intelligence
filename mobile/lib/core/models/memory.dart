import 'json_utils.dart';

/// The origin of a memory, inferred from its tags (the backend has no explicit
/// source column). Drives the leading icon on a memory card.
enum MemorySource {
  /// Typed by the user.
  manual,

  /// Extracted from an uploaded file.
  file,

  /// Synced from a wearable device.
  device,

  /// Written by an AI export import.
  ai,
}

/// A single brain memory (`/memory` list row, `/memory/search` result, or
/// `/memory/{id}`).
class Memory {
  /// Constructs a memory.
  const Memory({
    required this.id,
    required this.title,
    required this.content,
    this.tags = const [],
    this.createdAt,
    this.updatedAt,
  });

  /// Stable id — `id` in list rows, `memory_id` in search/detail responses.
  final String id;
  final String title;
  final String content;
  final List<String> tags;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  /// Decodes a memory from either the list or search/detail shape.
  factory Memory.fromJson(Map<String, dynamic> json) => Memory(
        id: asStr(json['id'] ?? json['memory_id']),
        title: asStr(json['title']),
        content: asStr(json['content']),
        tags: asStrList(json['tags']),
        createdAt: asDate(json['created_at']),
        updatedAt: asDate(json['updated_at']),
      );

  /// Best-effort source classification from tags.
  MemorySource get source {
    final lower = tags.map((t) => t.toLowerCase());
    if (lower.any((t) => t.contains('file') || t.contains('document') || t.contains('upload'))) {
      return MemorySource.file;
    }
    if (lower.any((t) => t.contains('device') || t.contains('watch') || t.contains('health'))) {
      return MemorySource.device;
    }
    if (lower.any((t) => t.contains('ai') || t.contains('claude') || t.contains('chatgpt') || t.contains('gemini'))) {
      return MemorySource.ai;
    }
    return MemorySource.manual;
  }

  /// Whether the content came from a file (rendered italic in Lora).
  bool get isFromFile => source == MemorySource.file;

  /// Rendered in italic Lora when the text is "imported" rather than typed —
  /// i.e. from a file or an AI export.
  bool get italicBody => source == MemorySource.file || source == MemorySource.ai;
}
