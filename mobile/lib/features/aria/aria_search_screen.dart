import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/music.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../providers/aria_player_provider.dart';
import 'aria_widgets.dart';

/// ARIA search & discovery — a mood discovery grid before typing, then a
/// results list of matching tracks from `GET /api/aria/search`.
class AriaSearchScreen extends ConsumerStatefulWidget {
  /// Creates the search screen.
  const AriaSearchScreen({super.key});

  @override
  ConsumerState<AriaSearchScreen> createState() => _AriaSearchScreenState();
}

class _AriaSearchScreenState extends ConsumerState<AriaSearchScreen> {
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
                        hintText: 'Search tracks, moods, topics…',
                        prefixIcon: Icon(Icons.search, size: 18),
                        isDense: true,
                      ),
                    ),
                  ),
                  TextButton(onPressed: () => Navigator.of(context).pop(), child: Text('Cancel', style: AppText.base.copyWith(color: c.accentPrimary))),
                ],
              ),
            ),
            Expanded(
              child: _debounced.isEmpty ? _discovery(context) : _results(context, _debounced),
            ),
          ],
        ),
      ),
    );
  }

  Widget _discovery(BuildContext context) {
    final c = context.c;
    final ready = ref.watch(ariaLibraryProvider).valueOrNull?.readyTracks ?? const <Track>[];
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Browse by mood', style: AppText.mono(size: 11, weight: FontWeight.w600).copyWith(color: c.textTertiary)),
        const SizedBox(height: AppDimens.space3),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: 1.7,
          children: [
            for (final m in Mood.values)
              GestureDetector(
                onTap: () {
                  setState(() {
                    _q = m.label;
                    _debounced = m.label;
                  });
                },
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(color: m.color, borderRadius: BorderRadius.circular(12)),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      const Spacer(),
                      Text(m.label, style: AppText.display(16).copyWith(color: Colors.white)),
                      Text('${ready.where((t) => t.mood == m).length} tracks',
                          style: AppText.mono(size: 11).copyWith(color: Colors.white.withValues(alpha: 0.8))),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }

  Widget _results(BuildContext context, String q) {
    final c = context.c;
    final async = ref.watch(ariaSearchProvider(q));
    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('Search failed. Try again.', style: AppText.serif(size: 15).copyWith(color: c.textTertiary))),
      data: (results) {
        if (results.isEmpty) {
          return Center(child: Text('No tracks match "$q".', style: AppText.serif(size: 15).copyWith(color: c.textTertiary)));
        }
        final ready = results.where((t) => !t.processing).toList();
        return ListView.builder(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          itemCount: results.length,
          itemBuilder: (_, i) {
            final t = results[i];
            return ListTile(
              contentPadding: EdgeInsets.zero,
              onTap: t.processing
                  ? null
                  : () {
                      ref.read(ariaPlayerProvider.notifier).playTrack(t, queueIds: ready.map((e) => e.id).toList());
                      Navigator.of(context).pop();
                    },
              leading: AlbumArt(title: t.title, mood: t.mood, size: 44, imageUrl: t.artUrl),
              title: Text(t.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppText.base.copyWith(color: c.textPrimary)),
              subtitle: Text(t.duration.isEmpty ? t.mood.label : '${t.mood.label} · ${t.duration}',
                  style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
            );
          },
        );
      },
    );
  }
}
