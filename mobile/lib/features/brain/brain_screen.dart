import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:infinite_scroll_pagination/infinite_scroll_pagination.dart';

import '../../core/models/memory.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/brain_pulse.dart';
import '../../core/widgets/progress_bar.dart';
import '../../core/widgets/states.dart';
import '../../core/widgets/toast.dart';
import '../../providers/brain_provider.dart';
import 'memory_card.dart';

/// The Brain screen: header, add-memory area, search, and an infinite,
/// pull-to-refresh memory list with swipe-to-delete.
class BrainScreen extends ConsumerStatefulWidget {
  /// Creates the Brain screen.
  const BrainScreen({super.key});

  @override
  ConsumerState<BrainScreen> createState() => _BrainScreenState();
}

class _BrainScreenState extends ConsumerState<BrainScreen> {
  static const _pageSize = 20;
  final _paging = PagingController<int, Memory>(firstPageKey: 1);
  final _addController = TextEditingController();
  final _searchController = TextEditingController();
  Timer? _searchDebounce;
  String _query = '';
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _paging.addPageRequestListener(_fetchPage);
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _paging.dispose();
    _addController.dispose();
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _fetchPage(int pageKey) async {
    try {
      final page = await ref.read(brainRepositoryProvider).page(
            page: pageKey,
            pageSize: _pageSize,
            query: _query.isEmpty ? null : _query,
          );
      if (page.hasMore) {
        _paging.appendPage(page.items, pageKey + 1);
      } else {
        _paging.appendLastPage(page.items);
      }
    } catch (e) {
      _paging.error = e;
    }
  }

  void _onSearchChanged(String value) {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 400), () {
      setState(() => _query = value.trim());
      _paging.refresh();
    });
  }

  Future<void> _save() async {
    final text = _addController.text.trim();
    if (text.isEmpty) return;
    setState(() => _saving = true);
    try {
      await ref.read(brainRepositoryProvider).addText(text);
      _addController.clear();
      _paging.refresh();
      ref.read(brainStatsProvider.notifier).refresh();
      if (mounted) AppToast.show(context, '✓ Added to your brain');
    } catch (e) {
      if (mounted) AppToast.show(context, '$e', isError: true);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete(Memory m) async {
    try {
      await ref.read(brainRepositoryProvider).delete(m.id);
      final items = List<Memory>.from(_paging.itemList ?? [])..removeWhere((e) => e.id == m.id);
      _paging.itemList = items;
      ref.read(brainStatsProvider.notifier).refresh();
      if (mounted) AppToast.show(context, 'Memory deleted');
    } catch (e) {
      if (mounted) AppToast.show(context, '$e', isError: true);
      _paging.refresh();
    }
  }

  void _expand(Memory m) {
    final c = context.c;
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetCtx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        maxChildSize: 0.9,
        builder: (_, scrollController) => ListView(
          controller: scrollController,
          padding: const EdgeInsets.all(AppDimens.space5),
          children: [
            Text(m.title, style: AppText.lg.copyWith(color: c.textPrimary)),
            const SizedBox(height: AppDimens.space3),
            Text(m.content, style: AppText.serif(italic: m.italicBody).copyWith(color: c.textSecondary)),
            const SizedBox(height: AppDimens.space5),
            Row(
              children: [
                AppButton(
                  label: 'Edit',
                  variant: AppButtonVariant.outlined,
                  icon: Icons.edit_outlined,
                  onPressed: () {
                    Navigator.of(sheetCtx).pop();
                    _edit(m);
                  },
                ),
                const SizedBox(width: AppDimens.space3),
                AppButton(
                  label: 'Delete',
                  variant: AppButtonVariant.ghost,
                  danger: true,
                  icon: Icons.delete_outline,
                  onPressed: () {
                    Navigator.of(sheetCtx).pop();
                    _delete(m);
                  },
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _edit(Memory m) async {
    final controller = TextEditingController(text: m.content);
    final updated = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Edit memory'),
        content: TextField(controller: controller, autofocus: true, maxLines: null, minLines: 4),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, controller.text.trim()), child: const Text('Save')),
        ],
      ),
    );
    if (updated == null || updated.isEmpty || updated == m.content) return;
    try {
      await ref.read(brainRepositoryProvider).update(m.id, content: updated);
      _paging.refresh();
      if (mounted) AppToast.show(context, '✓ Saved');
    } catch (e) {
      if (mounted) AppToast.show(context, '$e', isError: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final stats = ref.watch(brainStatsProvider);
    final count = stats.valueOrNull?.total ?? 0;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(AppDimens.space4, AppDimens.space4, AppDimens.space4, 0),
              child: Column(
                children: [
                  const BrainPulse(size: 48),
                  const SizedBox(height: AppDimens.space2),
                  Text('Your Brain', style: AppText.xl.copyWith(color: c.textPrimary)),
                  Text('$count memories', style: AppText.mono(size: 12).copyWith(color: c.textSecondary)),
                  const SizedBox(height: AppDimens.space2),
                  Text(
                    'Everything you share here makes the platform smarter.',
                    textAlign: TextAlign.center,
                    style: AppText.serif(size: 14).copyWith(color: c.textTertiary),
                  ),
                  const SizedBox(height: AppDimens.space4),
                  _AddMemoryBox(controller: _addController, saving: _saving, onSave: _save),
                  const SizedBox(height: AppDimens.space3),
                  TextField(
                    controller: _searchController,
                    onChanged: _onSearchChanged,
                    decoration: const InputDecoration(
                      hintText: 'Search your memories',
                      prefixIcon: Icon(Icons.search, size: 20),
                    ),
                  ),
                  const SizedBox(height: AppDimens.space3),
                ],
              ),
            ),
            Expanded(
              child: count == 0 && _query.isEmpty
                  ? const EmptyState(
                      icon: Icons.psychology_outlined,
                      message: 'This is where your brain lives. Tell it who you are, '
                          'paste what you know, or upload a file to get started.',
                    )
                  : RefreshIndicator(
                      color: c.brainAmber,
                      onRefresh: () async {
                        _paging.refresh();
                        ref.read(brainStatsProvider.notifier).refresh();
                      },
                      child: CustomScrollView(
                        slivers: [
                          if (count > 0 && _query.isEmpty)
                            SliverToBoxAdapter(
                              child: Padding(
                                padding: const EdgeInsets.fromLTRB(
                                    AppDimens.space4, 0, AppDimens.space4, AppDimens.space4),
                                child: _BrainImpactPanel(memoryCount: count),
                              ),
                            ),
                          SliverPadding(
                            padding: const EdgeInsets.fromLTRB(
                                AppDimens.space4, 0, AppDimens.space4, AppDimens.space6),
                            sliver: PagedSliverList<int, Memory>(
                              pagingController: _paging,
                              builderDelegate: PagedChildBuilderDelegate<Memory>(
                                itemBuilder: (_, m, __) => Padding(
                                  padding: const EdgeInsets.only(bottom: AppDimens.space3),
                                  child: Dismissible(
                                    key: ValueKey(m.id),
                                    direction: DismissDirection.endToStart,
                                    background: _DeleteBackground(color: c.danger),
                                    onDismissed: (_) => _delete(m),
                                    child: MemoryCard(memory: m, onTap: () => _expand(m)),
                                  ),
                                ),
                                firstPageProgressIndicatorBuilder: (_) => const ShimmerList(),
                                newPageProgressIndicatorBuilder: (_) => const Padding(
                                  padding: EdgeInsets.all(AppDimens.space4),
                                  child: Center(child: ShimmerBox(height: 14, width: 120)),
                                ),
                                firstPageErrorIndicatorBuilder: (_) => ErrorRetry(
                                  message: 'Couldn\'t load your memories.',
                                  onRetry: _paging.refresh,
                                ),
                                noItemsFoundIndicatorBuilder: (_) => EmptyState(
                                  message: _query.isEmpty
                                      ? 'No memories yet.'
                                      : 'Nothing matches "$_query".',
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

/// "Your brain powers" — four accent progress bars showing how much each
/// module has to work with, derived from the brain's size. Bars under 50% show
/// a hint on how to improve them.
class _BrainImpactPanel extends StatelessWidget {
  const _BrainImpactPanel({required this.memoryCount});
  final int memoryCount;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    // No per-module metric exists server-side; derive a readiness from brain
    // size. Pulse/Signal grow fastest; Health/Finances need their own uploads.
    double cap(double v) => v.clamp(0.0, 1.0);
    final rows = <({String label, double value, String? hint})>[
      (label: 'Pulse', value: cap(memoryCount / 10), hint: 'Add interests to sharpen your feed'),
      (label: 'Signal', value: cap(memoryCount / 14), hint: 'More topics mean richer videos'),
      (label: 'Health', value: cap(memoryCount / 40), hint: 'Connect a device or upload a health file'),
      (label: 'Finances', value: cap(memoryCount / 40), hint: 'Upload a statement to improve'),
    ];
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Your brain powers', style: AppText.md.copyWith(color: c.textPrimary)),
          const SizedBox(height: AppDimens.space3),
          for (final r in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: AppDimens.space3),
              child: AppProgressBar(
                value: r.value,
                label: r.label,
                color: c.accentPrimary,
                hint: r.value < 0.5 ? r.hint : null,
              ),
            ),
        ],
      ),
    );
  }
}

class _AddMemoryBox extends StatelessWidget {
  const _AddMemoryBox({required this.controller, required this.saving, required this.onSave});
  final TextEditingController controller;
  final bool saving;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      padding: const EdgeInsets.all(AppDimens.space3),
      decoration: BoxDecoration(
        color: c.backgroundSurface,
        borderRadius: BorderRadius.circular(AppDimens.cardRadius),
        border: Border.all(color: c.borderSubtle),
      ),
      child: Column(
        children: [
          TextField(
            controller: controller,
            minLines: 3,
            maxLines: 6,
            style: AppText.serif().copyWith(color: c.textPrimary),
            decoration: const InputDecoration(
              hintText: 'Add something to your brain…',
              border: InputBorder.none,
              enabledBorder: InputBorder.none,
              focusedBorder: InputBorder.none,
              filled: false,
            ),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              AppButton(label: 'Save', onPressed: onSave, loading: saving),
            ],
          ),
        ],
      ),
    );
  }
}

class _DeleteBackground extends StatelessWidget {
  const _DeleteBackground({required this.color});
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: Alignment.centerRight,
      padding: const EdgeInsets.symmetric(horizontal: AppDimens.space5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(AppDimens.cardRadius),
      ),
      child: Icon(Icons.delete_outline, color: color),
    );
  }
}
