import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/post.dart';
import '../../core/theme/app_colors.dart';
import '../../core/widgets/feed_chip.dart';
import '../../core/widgets/masthead.dart';
import '../../core/widgets/states.dart';
import '../../core/widgets/toast.dart';
import '../../providers/feed_seen_provider.dart';
import '../../providers/pulse_provider.dart';
import 'post_card.dart';
import 'post_reading_screen.dart';
import 'pulse_filter_sheet.dart';

/// The editorial PULSE feed: masthead → tone chips → featured hero → variable
/// format cards (with paired Format-B duos). A curated magazine, not a doom-feed.
class PulseScreen extends ConsumerStatefulWidget {
  /// Creates the PULSE screen.
  const PulseScreen({super.key});

  @override
  ConsumerState<PulseScreen> createState() => _PulseScreenState();
}

class _PulseScreenState extends ConsumerState<PulseScreen> {
  final Map<String, bool> _votes = {}; // postId → true(like)/false(dislike)

  static const _tones = ['all', 'informative', 'satirical', 'critical', 'supportive'];

  @override
  void initState() {
    super.initState();
    // Opening PULSE clears its nav presence dot.
    WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(feedSeenProvider.notifier).markPulseSeen());
  }

  Future<void> _vote(Post p, bool like) async {
    setState(() => _votes[p.id] = like);
    try {
      await ref.read(pulseRepositoryProvider).react(p.id, like: like);
      if (mounted) AppToast.show(context, '✓ Feedback saved');
    } catch (_) {/* best-effort */}
  }

  void _open(Post p) => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => PostReadingScreen(post: p, initialVote: _votes[p.id], onVote: _vote)),
      );

  @override
  Widget build(BuildContext context) {
    final filter = ref.watch(pulseFilterProvider);
    final feed = ref.watch(pulseFeedProvider);

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            Masthead(
              title: 'PULSE',
              actionIcon: Icons.tune,
              onAction: () => showPulseFilterSheet(context, ref),
            ),
            FeedChipRow(
              chips: [
                for (final t in _tones)
                  FeedChip(
                    label: t == 'all' ? 'All' : '${t[0].toUpperCase()}${t.substring(1)}',
                    active: filter.tone == t,
                    color: _toneColor(context, t),
                    onTap: () => ref.read(pulseFilterProvider.notifier).setTone(t),
                  ),
              ],
            ),
            Expanded(
              child: feed.when(
                loading: () => const ShimmerList(),
                error: (e, _) => ErrorRetry(
                  message: e is ApiException ? e.message : 'Couldn\'t load your feed.',
                  onRetry: () => ref.read(pulseFeedProvider.notifier).refresh(),
                ),
                data: (posts) => _feed(context, posts, filter),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _feed(BuildContext context, List<Post> posts, PulseFilter filter) {
    final c = context.c;
    final filtered = posts.where((p) {
      final toneOk = filter.tone == 'all' || (p.tone?.toLowerCase() == filter.tone);
      final creatorOk = filter.creatorId == null || p.creatorSlug == filter.creatorId;
      return toneOk && creatorOk;
    }).toList();

    if (filtered.isEmpty) {
      return RefreshIndicator(
        color: c.brainAmber,
        onRefresh: () => ref.read(pulseFeedProvider.notifier).refresh(),
        child: ListView(children: const [
          SizedBox(height: 80),
          EmptyState(message: 'Nothing here yet. Add to your brain and your feed will fill with stories.'),
        ]),
      );
    }

    // Featured = highest-scoring post in the current filter.
    final featured = filtered.reduce((a, b) => a.score >= b.score ? a : b);
    final rest = filtered.where((p) => p.id != featured.id).toList();

    // Pair consecutive Format-B (text-only) posts into duo rows.
    final rows = <List<Post>>[];
    for (var i = 0; i < rest.length; i++) {
      final p = rest[i];
      if (p.format == PostFormat.textOnly &&
          i + 1 < rest.length &&
          rest[i + 1].format == PostFormat.textOnly) {
        rows.add([p, rest[i + 1]]);
        i++;
      } else {
        rows.add([p]);
      }
    }

    return RefreshIndicator(
      color: c.brainAmber,
      onRefresh: () => ref.read(pulseFeedProvider.notifier).refresh(),
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
        itemCount: rows.length + 1,
        separatorBuilder: (_, __) => const SizedBox(height: 14),
        itemBuilder: (_, index) {
          if (index == 0) {
            return FeaturedPostCard(post: featured, vote: _votes[featured.id], onVote: _vote, onOpen: () => _open(featured));
          }
          final row = rows[index - 1];
          if (row.length == 2) {
            return Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(child: FormatBCard(post: row[0], compact: true, vote: _votes[row[0].id], onVote: _vote, onOpen: () => _open(row[0]))),
                const SizedBox(width: 8),
                Expanded(child: FormatBCard(post: row[1], compact: true, vote: _votes[row[1].id], onVote: _vote, onOpen: () => _open(row[1]))),
              ],
            );
          }
          return PostCard(post: row[0], vote: _votes[row[0].id], onVote: _vote, onOpen: () => _open(row[0]));
        },
      ),
    );
  }
}

/// The tone's semantic colour for chips/pills ('all' → accent).
Color _toneColor(BuildContext context, String tone) {
  final c = context.c;
  return switch (tone) {
    'critical' => c.danger,
    'satirical' => c.brainAmber,
    'supportive' => c.success,
    'informative' => c.accentPrimary,
    _ => c.accentPrimary,
  };
}
