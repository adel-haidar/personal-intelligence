import 'package:chewie/chewie.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:video_player/video_player.dart';

import '../../core/models/video.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/creator_avatar.dart';
import '../../core/widgets/feed_chip.dart';
import '../../core/widgets/score_badge.dart';
import '../../core/widgets/states.dart';
import '../../core/widgets/toast.dart';
import '../../core/widgets/vote_button.dart';
import '../../providers/signal_provider.dart';
import 'signal_cards.dart';

/// Full-screen video playback with title, creator, description, like/dislike,
/// and a Sources expander.
class VideoPlayerScreen extends ConsumerStatefulWidget {
  /// Creates the player for [videoId].
  const VideoPlayerScreen({super.key, required this.videoId});

  final String videoId;

  @override
  ConsumerState<VideoPlayerScreen> createState() => _VideoPlayerScreenState();
}

class _VideoPlayerScreenState extends ConsumerState<VideoPlayerScreen> {
  VideoPlayerController? _video;
  ChewieController? _chewie;
  bool? _vote;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _init());
  }

  void _init() {
    final video = ref.read(videoByIdProvider(widget.videoId));
    final url = video?.videoUrl;
    if (url == null || url.isEmpty) return;
    final controller = VideoPlayerController.networkUrl(Uri.parse(url));
    _video = controller;
    controller.initialize().then((_) {
      if (!mounted) return;
      setState(() {
        _chewie = ChewieController(
          videoPlayerController: controller,
          autoPlay: true,
          looping: false,
          materialProgressColors: ChewieProgressColors(
            playedColor: context.c.brainAmber,
            handleColor: context.c.brainAmber,
            backgroundColor: context.c.borderMedium,
            bufferedColor: context.c.borderSubtle,
          ),
        );
      });
      controller.addListener(_watchListener);
    });
  }

  void _watchListener() {
    final v = _video;
    if (v == null || !v.value.isInitialized) return;
    final pos = v.value.position;
    final dur = v.value.duration;
    if (dur.inSeconds > 0 && pos >= dur - const Duration(seconds: 1)) {
      ref.read(signalProvider.notifier).markWatched(widget.videoId);
      v.removeListener(_watchListener);
    }
  }

  void _react(bool like) {
    setState(() => _vote = like);
    ref.read(signalProvider.notifier).react(widget.videoId, like: like);
    AppToast.show(context, '✓ Feedback saved');
  }

  @override
  void dispose() {
    _chewie?.dispose();
    _video?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final Video? video = ref.watch(videoByIdProvider(widget.videoId));

    return Scaffold(
      appBar: AppBar(),
      body: video == null
          ? const EmptyState(message: 'This video isn\'t available right now.')
          : ListView(
              children: [
                AspectRatio(
                  aspectRatio: 16 / 9,
                  child: Container(
                    color: Colors.black,
                    child: _chewie != null
                        ? Chewie(controller: _chewie!)
                        : Center(
                            child: video.isProcessing
                                ? Text('This video is still being prepared. Check back in a few minutes.',
                                    textAlign: TextAlign.center,
                                    style: AppText.sm.copyWith(color: Colors.white70))
                                : const CircularProgressIndicator(),
                          ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(AppDimens.space5),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(video.title, style: AppText.display(20).copyWith(color: c.textPrimary)),
                      const SizedBox(height: AppDimens.space3),
                      Wrap(
                        spacing: AppDimens.space3,
                        runSpacing: AppDimens.space2,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              CreatorAvatar(name: video.creatorName, imageUrl: video.creatorAvatar, size: 20),
                              const SizedBox(width: 6),
                              Text(video.creatorName, style: AppText.sm.copyWith(color: c.textSecondary)),
                            ],
                          ),
                          if (video.category != null) FeedChip(label: video.category!, active: false, onTap: () {}),
                        ],
                      ),
                      if (video.description != null) ...[
                        const SizedBox(height: AppDimens.space4),
                        Text(video.description!, style: AppText.serif(size: 15).copyWith(color: c.textSecondary)),
                      ],
                      const SizedBox(height: AppDimens.space5),
                      Row(
                        children: [
                          ScoreText(score: video.score, size: 13),
                          const Spacer(),
                          VoteButton(icon: Icons.thumb_up_outlined, label: 'Like', color: c.success, active: _vote == true, onTap: () => _react(true)),
                          const SizedBox(width: AppDimens.space2),
                          VoteButton(icon: Icons.thumb_down_outlined, label: 'Dislike', color: c.danger, active: _vote == false, onTap: () => _react(false)),
                        ],
                      ),
                      const SizedBox(height: AppDimens.space3),
                      Theme(
                        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                        child: ExpansionTile(
                          tilePadding: EdgeInsets.zero,
                          title: Text('Sources', style: AppText.md.copyWith(color: c.textPrimary)),
                          childrenPadding: const EdgeInsets.only(bottom: AppDimens.space3),
                          children: [
                            Align(
                              alignment: Alignment.centerLeft,
                              child: Text(
                                'Sources aren\'t listed for this video yet.',
                                style: AppText.sm.copyWith(color: c.textTertiary),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                ..._moreLikeThis(video),
                const SizedBox(height: AppDimens.space6),
              ],
            ),
    );
  }

  /// "More like this" — other ready videos in the same category.
  List<Widget> _moreLikeThis(Video video) {
    final all = ref.watch(signalProvider).valueOrNull ?? const [];
    final related = all
        .where((v) => v.id != video.id && v.status == VideoStatus.ready && v.category != null && v.category == video.category)
        .take(8)
        .toList();
    if (related.isEmpty) return const [];
    return [
      const SectionHead(title: 'More like this'),
      VideoRow(children: [
        for (final v in related) VideoRowCard(video: v, onTap: () => context.push('/signal/video/${v.id}')),
      ]),
    ];
  }
}
