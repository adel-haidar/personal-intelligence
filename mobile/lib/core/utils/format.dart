import 'package:intl/intl.dart';

/// Small formatting helpers shared across screens.
class Format {
  Format._();

  /// Relative time like "just now", "5m ago", "3h ago", "2d ago", else a date.
  static String relative(DateTime? dt) {
    if (dt == null) return '';
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inSeconds < 60) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    return DateFormat('d MMM').format(dt);
  }

  /// Short timestamp for JetBrains Mono labels ("14:32" or "12 Jun").
  static String shortTime(DateTime? dt) {
    if (dt == null) return '';
    final now = DateTime.now();
    if (dt.year == now.year && dt.month == now.month && dt.day == now.day) {
      return DateFormat('HH:mm').format(dt);
    }
    return DateFormat('d MMM').format(dt);
  }

  /// Greeting based on the hour of day.
  static String greeting() {
    final h = DateTime.now().hour;
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
  }

  /// A currency-ish number ("1,240" / "1,240.50").
  static String money(num value) => NumberFormat('#,##0.##').format(value);
}
