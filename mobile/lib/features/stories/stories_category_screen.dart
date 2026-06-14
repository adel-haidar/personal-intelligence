import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/models/story.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/feed_chip.dart';
import '../../core/widgets/states.dart';
import '../../providers/stories_provider.dart';
import 'stories_widgets.dart';

/// Category browse — a responsive poster grid with Type filter (All/Films/Series).
/// Sourced from the loaded STORIES library.
class StoriesCategoryScreen extends ConsumerStatefulWidget {
  /// Creates the browse screen for [category] ('All' shows everything).
  const StoriesCategoryScreen({super.key, this.category = 'All'});

  final String category;

  @override
  ConsumerState<StoriesCategoryScreen> createState() => _StoriesCategoryScreenState();
}

class _StoriesCategoryScreenState extends ConsumerState<StoriesCategoryScreen> {
  String _type = 'All'; // All / Films / Series

  bool _inCat(String? cat) => widget.category == 'All' || cat == widget.category;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final async = ref.watch(storiesLibraryProvider);

    return Scaffold(
      appBar: AppBar(title: Text(widget.category, style: AppText.md.copyWith(color: c.textPrimary))),
      body: async.when(
        loading: () => const ShimmerList(),
        error: (e, _) => ErrorRetry(
          message: 'Couldn\'t load the catalog.',
          onRetry: () => ref.read(storiesLibraryProvider.notifier).refresh(),
        ),
        data: (lib) => _grid(context, lib),
      ),
    );
  }

  Widget _grid(BuildContext context, StoriesLibrary lib) {
    final c = context.c;
    final films = lib.films.where((f) => _inCat(f.category)).toList();
    final series = lib.series.where((s) => _inCat(s.category)).toList();

    final items = <Widget>[];
    if (_type != 'Series') {
      items.addAll(films.map(_filmPoster));
    }
    if (_type != 'Films') {
      items.addAll(series.map(_seriesPoster));
    }

    final cellW = (MediaQuery.of(context).size.width - 16 * 2 - 14) / 2;

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
      children: [
        Text('${films.length} films · ${series.length} series',
            style: AppText.mono(size: 12).copyWith(color: c.textTertiary)),
        const SizedBox(height: 12),
        Row(
          children: [
            for (final t in const ['All', 'Films', 'Series']) ...[
              FeedChip(label: t, active: _type == t, onTap: () => setState(() => _type = t)),
              const SizedBox(width: 8),
            ],
          ],
        ),
        const SizedBox(height: 16),
        if (items.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 48),
            child: Center(child: Text('Nothing here yet.', style: AppText.serif(size: 16).copyWith(color: c.textTertiary))),
          )
        else
          Wrap(
            spacing: 14,
            runSpacing: 16,
            children: [for (final w in items) SizedBox(width: cellW, child: w)],
          ),
      ],
    );
  }

  Widget _filmPoster(Film f) => StoryPoster(
        seed: f.title,
        title: f.title,
        width: double.infinity,
        genre: f.categoryChip,
        duration: f.duration,
        processing: f.processing,
        imageUrl: f.posterUrl ?? f.thumbnailUrl,
        progress: f.started ? f.watchProgress?.percent : null,
        subLabel: f.processing
            ? null
            : (f.started && (f.watchProgress?.leftLabel.isNotEmpty ?? false) ? f.watchProgress!.leftLabel : null),
        subIsMono: true,
        subColor: context.c.textTertiary,
        onTap: () => context.push('${Routes.stories}/film/${f.id}'),
      );

  Widget _seriesPoster(Series s) => StoryPoster(
        seed: s.title,
        title: s.title,
        width: double.infinity,
        isSeries: true,
        imageUrl: s.posterUrl ?? s.thumbnailUrl,
        subLabel: s.effectiveEpisodeCount > 0 ? '${s.effectiveEpisodeCount} episodes' : null,
        onTap: () => context.push('${Routes.stories}/series/${s.id}'),
      );
}
