import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/seeded.dart';
import '../../providers/stories_provider.dart';
import 'stories_widgets.dart';

/// STORIES search — category discovery grid before typing, vertical results
/// after. Backed by `GET /api/stories/search`.
class StoriesSearchScreen extends ConsumerStatefulWidget {
  /// Creates the search screen.
  const StoriesSearchScreen({super.key});

  @override
  ConsumerState<StoriesSearchScreen> createState() => _StoriesSearchScreenState();
}

class _StoriesSearchScreenState extends ConsumerState<StoriesSearchScreen> {
  String _q = '';
  String _debounced = '';
  Timer? _debounce;

  void _onChanged(String v) {
    setState(() => _q = v);
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      if (mounted) setState(() => _debounced = v.trim());
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      autofocus: true,
                      onChanged: _onChanged,
                      decoration: const InputDecoration(
                        hintText: 'Search films and series…',
                        prefixIcon: Icon(Icons.search, size: 18),
                        isDense: true,
                      ),
                    ),
                  ),
                  TextButton(onPressed: () => Navigator.of(context).pop(), child: Text('Cancel', style: AppText.base.copyWith(color: c.accentPrimary))),
                ],
              ),
            ),
            Expanded(child: _debounced.isEmpty ? _discovery(context) : _results(context, _debounced)),
          ],
        ),
      ),
    );
  }

  Widget _discovery(BuildContext context) {
    final c = context.c;
    final categories = ref.watch(storiesLibraryProvider).valueOrNull?.categories ?? const [];
    if (categories.isEmpty) {
      return Center(child: Text('Type to search films and series.', style: AppText.serif(size: 15).copyWith(color: c.textTertiary)));
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Browse by category', style: AppText.mono(size: 11, weight: FontWeight.w600).copyWith(color: c.textTertiary)),
        const SizedBox(height: AppDimens.space3),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final cat in categories)
              GestureDetector(
                onTap: () {
                  setState(() {
                    _q = cat.name;
                    _debounced = cat.name;
                  });
                },
                child: Container(
                  width: (MediaQuery.of(context).size.width - 16 * 2 - 12) / 2,
                  height: 64,
                  padding: const EdgeInsets.all(12),
                  alignment: Alignment.bottomLeft,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    gradient: LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: [Color.alphaBlend(Seeded.color(cat.name).withValues(alpha: 0.5), c.backgroundRaised), c.backgroundRaised],
                    ),
                  ),
                  child: Text(cat.name, style: AppText.mono(size: 12, weight: FontWeight.w600).copyWith(color: c.textPrimary)),
                ),
              ),
          ],
        ),
      ],
    );
  }

  Widget _results(BuildContext context, String q) {
    final c = context.c;
    final async = ref.watch(storiesSearchProvider(q));
    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('Search failed. Try again.', style: AppText.serif(size: 16).copyWith(color: c.textTertiary))),
      data: (res) {
        final films = res.films;
        final series = res.series;
        if (films.isEmpty && series.isEmpty) {
          return Center(child: Text('No stories match "$q".', style: AppText.serif(size: 16).copyWith(color: c.textTertiary)));
        }
        return ListView(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          children: [
            for (final f in films)
              _resultRow(
                context,
                seed: f.title,
                imageUrl: f.posterUrl ?? f.thumbnailUrl,
                title: f.title,
                meta: [f.categoryChip, f.duration].where((s) => s != null && s.isNotEmpty).join(' · '),
                onTap: () => context.push('${Routes.stories}/film/${f.id}'),
              ),
            for (final s in series)
              _resultRow(
                context,
                seed: s.title,
                imageUrl: s.posterUrl ?? s.thumbnailUrl,
                title: s.title,
                meta: 'Series${s.effectiveEpisodeCount > 0 ? ' · ${s.effectiveEpisodeCount} episodes' : ''}',
                onTap: () => context.push('${Routes.stories}/series/${s.id}'),
              ),
          ],
        );
      },
    );
  }

  Widget _resultRow(BuildContext context,
      {required String seed, String? imageUrl, required String title, required String meta, required VoidCallback onTap}) {
    final c = context.c;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: SizedBox(
                width: 44,
                height: 66,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    DecoratedBox(decoration: Seeded.thumb(seed, c.backgroundRaised)),
                    PosterImage(url: imageUrl),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.base.copyWith(color: c.textPrimary, fontWeight: FontWeight.w500)),
                  if (meta.isNotEmpty) Text(meta, style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
