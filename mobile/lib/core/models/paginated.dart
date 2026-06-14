import 'json_utils.dart';

/// A page of `T` from a `{items, total, page, pages}` backend envelope —
/// the shape used by `/memory`, `/content/posts`, `/content/videos`, `/topics`.
class Paginated<T> {
  /// Wraps a decoded page.
  const Paginated({
    required this.items,
    required this.total,
    required this.page,
    required this.pages,
  });

  /// The rows for this page.
  final List<T> items;

  /// Total row count across all pages.
  final int total;

  /// 1-based index of this page.
  final int page;

  /// Total number of pages.
  final int pages;

  /// True if a further page exists after this one.
  bool get hasMore => page < pages;

  /// Decodes an envelope, mapping each item with [fromItem].
  factory Paginated.fromJson(Map<String, dynamic> json, T Function(Map<String, dynamic>) fromItem) {
    final rawItems = (json['items'] as List?) ?? const [];
    return Paginated<T>(
      items: rawItems
          .whereType<Map>()
          .map((e) => fromItem(Map<String, dynamic>.from(e)))
          .toList(),
      total: asInt(json['total']) ?? rawItems.length,
      page: asInt(json['page']) ?? 1,
      pages: asInt(json['pages']) ?? 1,
    );
  }
}
