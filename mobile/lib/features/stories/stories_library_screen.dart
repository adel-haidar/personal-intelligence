import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/story.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/masthead.dart';
import '../../core/widgets/states.dart';
import '../../providers/feed_seen_provider.dart';
import '../../providers/stories_provider.dart';
import '../signal/signal_cards.dart' show SectionHead;
import 'stories_widgets.dart';

/// The STORIES library — poster-first: Continue watching → Featured hero →
/// New films → Series → By category. API-backed (`GET /api/stories`).
class StoriesLibraryScreen extends ConsumerStatefulWidget {
  /// Creates the library screen.
  const StoriesLibraryScreen({super.key});

  @override
  ConsumerState<StoriesLibraryScreen> createState() => _StoriesLibraryScreenState();
}

class _StoriesLibraryScreenState extends ConsumerState<StoriesLibraryScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(feedSeenProvider.notifier).markStoriesSeen());
  }

  void _openFilm(Film f) => context.push('${Routes.stories}/film/${f.id}');
  void _openSeries(Series s) => context.push('${Routes.stories}/series/${s.id}');
  void _playFilm(Film f) => context.push('${Routes.storiesPlayer}?film=${f.id}');
  void _playContinue(ContinueWatching it) {
    if (it.isEpisode) {
      context.push('${Routes.storiesPlayer}?episode=${it.contentId}');
    } else {
      context.push('${Routes.storiesPlayer}?film=${it.contentId}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(storiesLibraryProvider);

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            Masthead(
              title: 'STORIES',
              actionIcon: Icons.search,
              onAction: () => context.push(Routes.storiesSearch),
            ),
            Expanded(
              child: async.when(
                loading: () => const ShimmerList(),
                error: (e, _) => ErrorRetry(
                  message: 'Couldn\'t load your library.',
                  onRetry: () => ref.read(storiesLibraryProvider.notifier).refresh(),
                ),
                data: (lib) {
                  if (lib.films.isEmpty && lib.series.isEmpty) {
                    return const EmptyState(
                      icon: Icons.movie_outlined,
                      message: 'No films yet. STORIES is generating from your brain.',
                    );
                  }
                  return _content(lib);
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _content(StoriesLibrary lib) {
    final c = context.c;
    final featured = lib.featured;
    final continueItems = lib.continueWatching;
    final newFilms = lib.films.where((f) => f.id != featured?.id).toList();
    final catsWith = lib.categories.where((cat) => _categoryItems(lib, cat.name, featured?.id).isNotEmpty).toList();

    return RefreshIndicator(
      onRefresh: () => ref.read(storiesLibraryProvider.notifier).refresh(),
      child: ListView(
        children: [
          if (continueItems.isNotEmpty) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
              child: Text('Continue watching',
                  style: AppText.label.copyWith(color: c.textTertiary, letterSpacing: 0.6)),
            ),
            _Row(children: [
              for (final it in continueItems)
                StoryPoster(
                  seed: it.title,
                  title: it.title,
                  width: 140,
                  imageUrl: it.thumbnailUrl,
                  progress: it.percent,
                  subLabel: it.leftLabel.isEmpty ? null : it.leftLabel,
                  subIsMono: true,
                  subColor: c.textTertiary,
                  showProgressOnly: true,
                  onTap: () => _playContinue(it),
                ),
            ]),
          ],
          if (featured != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 18, 16, 0),
              child: StoriesHero(
                seed: featured.title,
                genre: featured.categoryChip,
                title: featured.title,
                premise: featured.premise ?? '',
                metaTrailing: featured.duration,
                imageUrl: featured.posterUrl ?? featured.thumbnailUrl,
                onPlay: () => _playFilm(featured),
                onOpen: () => _openFilm(featured),
              ),
            ),
          if (newFilms.isNotEmpty) ...[
            SectionHead(title: 'New films', onSeeAll: () => context.push('${Routes.storiesCategory}?cat=All')),
            _Row(children: [for (final f in newFilms) _filmPoster(f)]),
          ],
          if (lib.series.isNotEmpty) ...[
            const SectionHead(title: 'Series'),
            _Row(children: [for (final s in lib.series) _seriesPoster(s)]),
          ],
          for (final cat in catsWith) ..._categorySection(lib, cat.name, featured?.id),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  List<Widget> _categorySection(StoriesLibrary lib, String cat, String? featuredId) {
    final items = _categoryItems(lib, cat, featuredId);
    if (items.isEmpty) return const [];
    return [
      SectionHead(title: cat, accent: true, onSeeAll: () => context.push('${Routes.storiesCategory}?cat=$cat')),
      _Row(children: [
        for (final item in items)
          if (item is Film) _filmPoster(item) else _seriesPoster(item as Series),
      ]),
    ];
  }

  List<Object> _categoryItems(StoriesLibrary lib, String cat, String? featuredId) {
    final out = <Object>[];
    for (final f in lib.films) {
      if (f.category == cat && f.id != featuredId) out.add(f);
    }
    for (final s in lib.series) {
      if (s.category == cat) out.add(s);
    }
    return out;
  }

  Widget _filmPoster(Film f) {
    final c = context.c;
    return StoryPoster(
      seed: f.title,
      title: f.title,
      genre: f.categoryChip,
      duration: f.duration,
      processing: f.processing,
      imageUrl: f.posterUrl ?? f.thumbnailUrl,
      progress: f.started ? f.watchProgress?.percent : null,
      subLabel: f.processing
          ? null
          : (f.started ? (f.watchProgress?.leftLabel.isEmpty ?? true ? null : f.watchProgress!.leftLabel) : null),
      subIsMono: true,
      subColor: c.textTertiary,
      onTap: () => _openFilm(f),
    );
  }

  Widget _seriesPoster(Series s) {
    return StoryPoster(
      seed: s.title,
      title: s.title,
      width: 180,
      isSeries: true,
      imageUrl: s.posterUrl ?? s.thumbnailUrl,
      subLabel: s.effectiveEpisodeCount > 0 ? '${s.effectiveEpisodeCount} episodes' : null,
      onTap: () => _openSeries(s),
    );
  }
}

/// A 16px-gutter horizontal poster row.
class _Row extends StatelessWidget {
  const _Row({required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(16, 2, 16, 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const SizedBox(width: 12),
            children[i],
          ],
        ],
      ),
    );
  }
}
