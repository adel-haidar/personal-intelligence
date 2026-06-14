import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/video.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/seeded.dart';
import '../../core/widgets/feed_chip.dart';
import '../../core/widgets/masthead.dart';
import '../../core/widgets/states.dart';
import '../../providers/feed_seen_provider.dart';
import '../../providers/signal_provider.dart';
import 'signal_cards.dart';

/// The editorial SIGNAL channel: masthead → category chips → featured hero →
/// Recent → by-category sections, plus inline search. Sections derive from the
/// videos' categories (the user's topic clusters) when present.
class SignalScreen extends ConsumerStatefulWidget {
  /// Creates the SIGNAL screen.
  const SignalScreen({super.key});

  @override
  ConsumerState<SignalScreen> createState() => _SignalScreenState();
}

class _SignalScreenState extends ConsumerState<SignalScreen> {
  String _cat = 'All';
  bool _searching = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(feedSeenProvider.notifier).markSignalSeen());
  }

  void _play(Video v) => context.push('/signal/video/${v.id}');

  @override
  Widget build(BuildContext context) {
    final videos = ref.watch(signalProvider);

    if (_searching) {
      return _SignalSearch(
        videos: videos.valueOrNull ?? const [],
        onCancel: () => setState(() => _searching = false),
        onPlay: _play,
      );
    }

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: videos.when(
          loading: () => const ShimmerList(),
          error: (e, _) => Column(children: [
            Masthead(title: 'SIGNAL', actionIcon: Icons.search, onAction: () {}),
            Expanded(
              child: ErrorRetry(
                message: e is ApiException ? e.message : 'Couldn\'t load your videos.',
                onRetry: () => ref.read(signalProvider.notifier).refresh(),
              ),
            ),
          ]),
          data: (list) => _content(context, list),
        ),
      ),
    );
  }

  Widget _content(BuildContext context, List<Video> all) {
    final c = context.c;
    // Categories present in the data (the user's topic clusters).
    final cats = <String>{for (final v in all) if (v.category != null) v.category!}.toList()..sort();
    final hasCats = cats.isNotEmpty;

    bool inCat(Video v) => _cat == 'All' || v.category == _cat;
    final filtered = all.where(inCat).toList();

    if (filtered.isEmpty) {
      return Column(
        children: [
          Masthead(title: 'SIGNAL', actionIcon: Icons.search, onAction: () => setState(() => _searching = true)),
          Expanded(
            child: EmptyState(
              icon: Icons.video_library_outlined,
              message: 'No videos yet. Add to your brain and your channel will fill up.',
            ),
          ),
        ],
      );
    }

    final ready = filtered.where((v) => v.status == VideoStatus.ready).toList();
    final featured = (ready.isEmpty ? filtered : ready).reduce((a, b) => a.score >= b.score ? a : b);
    final recent = filtered.where((v) => v.id != featured.id).toList();

    return RefreshIndicator(
      color: c.brainAmber,
      onRefresh: () => ref.read(signalProvider.notifier).refresh(),
      child: ListView(
        children: [
          Masthead(title: 'SIGNAL', actionIcon: Icons.search, onAction: () => setState(() => _searching = true)),
          if (hasCats)
            FeedChipRow(
              chips: [
                for (final cat in ['All', ...cats])
                  FeedChip(label: cat, active: _cat == cat, onTap: () => setState(() => _cat = cat)),
              ],
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: FeaturedVideoHero(video: featured, onPlay: () => _play(featured)),
          ),
          SectionHead(title: _cat == 'All' ? 'Recent' : _cat, onSeeAll: () {}),
          VideoRow(children: [for (final v in recent) VideoRowCard(video: v, onTap: () => _play(v))]),
          if (_cat == 'All')
            for (final cat in cats)
              ..._categorySection(cat, all.where((v) => v.category == cat && v.id != featured.id).toList()),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  List<Widget> _categorySection(String cat, List<Video> vids) {
    if (vids.isEmpty) return const [];
    if (vids.length == 1) {
      return [
        SectionHead(title: cat, accent: true, onSeeAll: () => setState(() => _cat = cat)),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: WideVideoCard(video: vids.first, onTap: () => _play(vids.first)),
        ),
      ];
    }
    return [
      SectionHead(title: cat, accent: true, onSeeAll: () => setState(() => _cat = cat)),
      VideoRow(children: [for (final v in vids) VideoRowCard(video: v, onTap: () => _play(v))]),
    ];
  }
}

/// Inline SIGNAL search: a search bar + Cancel, then a vertical list of compact
/// result rows.
class _SignalSearch extends StatefulWidget {
  const _SignalSearch({required this.videos, required this.onCancel, required this.onPlay});
  final List<Video> videos;
  final VoidCallback onCancel;
  final ValueChanged<Video> onPlay;

  @override
  State<_SignalSearch> createState() => _SignalSearchState();
}

class _SignalSearchState extends State<_SignalSearch> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final q = _q.trim().toLowerCase();
    final results = q.isEmpty
        ? <Video>[]
        : widget.videos
            .where((v) =>
                v.title.toLowerCase().contains(q) ||
                v.creatorName.toLowerCase().contains(q) ||
                (v.category?.toLowerCase().contains(q) ?? false))
            .toList();

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      autofocus: true,
                      onChanged: (v) => setState(() => _q = v),
                      decoration: const InputDecoration(
                        hintText: 'Search videos by topic…',
                        prefixIcon: Icon(Icons.search, size: 18),
                        isDense: true,
                      ),
                    ),
                  ),
                  TextButton(onPressed: widget.onCancel, child: Text('Cancel', style: AppText.base.copyWith(color: c.accentPrimary))),
                ],
              ),
            ),
            Expanded(
              child: q.isEmpty
                  ? Center(
                      child: Text('Search across ${widget.videos.length} videos in your library.',
                          style: AppText.sm.copyWith(color: c.textTertiary)),
                    )
                  : results.isEmpty
                      ? Center(child: Text('No videos match "$_q".', style: AppText.sm.copyWith(color: c.textTertiary)))
                      : ListView.builder(
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          itemCount: results.length,
                          itemBuilder: (_, i) {
                            final v = results[i];
                            return InkWell(
                              onTap: v.status == VideoStatus.ready ? () => widget.onPlay(v) : null,
                              child: Padding(
                                padding: const EdgeInsets.symmetric(vertical: 8),
                                child: Row(
                                  children: [
                                    Container(
                                      width: 56,
                                      height: 42,
                                      decoration: Seeded.thumb(v.creatorName, c.backgroundRaised).copyWith(
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                    ),
                                    const SizedBox(width: 12),
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(v.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                                              style: AppText.base.copyWith(color: c.textPrimary, fontWeight: FontWeight.w500)),
                                          Text('${v.creatorName.split(' ').first} · ${v.durationLabel}',
                                              style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                                        ],
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            );
                          },
                        ),
            ),
          ],
        ),
      ),
    );
  }
}
