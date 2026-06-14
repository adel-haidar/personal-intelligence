import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../../core/models/post.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/seeded.dart';
import '../../core/widgets/creator_avatar.dart';
import '../../core/widgets/score_badge.dart';
import '../../core/widgets/source_card.dart';
import '../../core/widgets/tone_pill.dart';
import '../../core/widgets/vote_button.dart';
import 'post_card.dart';

/// Full-screen reading mode for a post — larger Lora body (line-height 1.75),
/// the topic as page title, sources, and a pinned Like/Dislike bar.
class PostReadingScreen extends StatefulWidget {
  /// Creates reading mode for [post].
  const PostReadingScreen({super.key, required this.post, required this.onVote, this.initialVote});

  final Post post;
  final PostVote onVote;
  final bool? initialVote;

  @override
  State<PostReadingScreen> createState() => _PostReadingScreenState();
}

class _PostReadingScreenState extends State<PostReadingScreen> {
  late bool? _vote = widget.initialVote;

  void _doVote(bool like) {
    setState(() => _vote = like);
    widget.onVote(widget.post, like);
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final p = widget.post;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                children: [
                  TextButton.icon(
                    style: TextButton.styleFrom(padding: EdgeInsets.zero, alignment: Alignment.centerLeft),
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.chevron_left, size: 18),
                    label: Text('Back to Pulse', style: AppText.sm.copyWith(color: c.accentPrimary)),
                  ),
                  const SizedBox(height: AppDimens.space3),
                  Row(
                    children: [
                      if (p.tone != null) ...[TonePill(tone: p.tone!), const SizedBox(width: 10)],
                      ScoreText(score: p.score, size: 12),
                      const SizedBox(width: 10),
                      Text('${p.readMinutes} min read', style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                    ],
                  ),
                  const SizedBox(height: AppDimens.space4),
                  Text(p.headline, style: AppText.xl.copyWith(color: c.textPrimary)),
                  const SizedBox(height: AppDimens.space4),
                  Row(
                    children: [
                      CreatorAvatar(name: p.creatorName, imageUrl: p.creatorAvatar, size: 32),
                      const SizedBox(width: 10),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(p.creatorName, style: AppText.md.copyWith(color: c.textPrimary)),
                          Text('@${p.creatorSlug}', style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: AppDimens.space5),
                  Text(p.body, style: AppText.serif(size: 16).copyWith(color: c.textPrimary, height: 1.75)),
                  if (p.imageUrl != null && p.imageUrl!.isNotEmpty) ...[
                    const SizedBox(height: AppDimens.space4),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: AspectRatio(
                        aspectRatio: 16 / 9,
                        child: CachedNetworkImage(
                          imageUrl: p.imageUrl!,
                          fit: BoxFit.cover,
                          errorWidget: (_, __, ___) => DecoratedBox(decoration: Seeded.thumb(p.creatorName, c.backgroundRaised)),
                        ),
                      ),
                    ),
                  ],
                  if (p.linkUrl != null) ...[
                    const SizedBox(height: AppDimens.space5),
                    Text('Sources', style: AppText.mono(size: 11, weight: FontWeight.w600).copyWith(color: c.textTertiary)),
                    const SizedBox(height: AppDimens.space2),
                    SourceCard(host: p.linkHost ?? 'source', title: p.headline, seedName: p.creatorName, url: p.linkUrl),
                  ],
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
              decoration: BoxDecoration(border: Border(top: BorderSide(color: c.borderSubtle))),
              child: Row(
                children: [
                  VoteButton(icon: Icons.arrow_upward, label: 'Like', color: c.success, active: _vote == true, onTap: () => _doVote(true)),
                  const SizedBox(width: 10),
                  VoteButton(icon: Icons.arrow_downward, label: 'Dislike', color: c.danger, active: _vote == false, onTap: () => _doVote(false)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
