import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../../core/models/post.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/seeded.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/creator_avatar.dart';
import '../../core/widgets/featured_hero.dart';
import '../../core/widgets/score_badge.dart';
import '../../core/widgets/source_card.dart';
import '../../core/widgets/tone_pill.dart';
import '../../core/widgets/vote_button.dart';

/// Signature for a like(true)/dislike(false) vote on a post.
typedef PostVote = void Function(Post post, bool like);

/// The featured story — hero treatment + an attached Like/Dislike/Open strip.
class FeaturedPostCard extends StatelessWidget {
  /// Creates the featured card.
  const FeaturedPostCard({super.key, required this.post, required this.onVote, required this.onOpen, this.vote});

  final Post post;
  final bool? vote;
  final PostVote onVote;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FeaturedHero(
          seedName: post.creatorName,
          imageUrl: post.imageUrl,
          onTap: onOpen,
          topLeft: post.tone != null ? TonePill(tone: post.tone!) : null,
          topRight: ScoreText(score: post.score, onDark: true),
          title: post.headline,
          metaName: post.creatorName,
          metaTrailing: '· ${post.readMinutes} min read',
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            VoteButton(icon: Icons.arrow_upward, label: '${post.scoreLabel} Like', color: c.success, active: vote == true, onTap: () => onVote(post, true)),
            const SizedBox(width: 6),
            VoteButton(icon: Icons.arrow_downward, label: 'Dislike', color: c.danger, active: vote == false, onTap: () => onVote(post, false)),
            const SizedBox(width: 6),
            VoteButton(icon: Icons.north_east, label: 'Open', color: c.accentPrimary, onTap: onOpen),
          ],
        ),
      ],
    );
  }
}

/// Dispatches a non-featured post to Format A (image), B (text), or C (source).
class PostCard extends StatelessWidget {
  /// Creates a post card.
  const PostCard({super.key, required this.post, required this.onVote, required this.onOpen, this.vote});

  final Post post;
  final bool? vote;
  final PostVote onVote;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    switch (post.format) {
      case PostFormat.externalSource:
        return _FormatC(post: post, vote: vote, onVote: onVote, onOpen: onOpen);
      case PostFormat.textOnly:
        return FormatBCard(post: post, vote: vote, onVote: onVote, onOpen: onOpen);
      case PostFormat.imagePost:
        return _FormatA(post: post, vote: vote, onVote: onVote, onOpen: onOpen);
    }
  }
}

class _FormatA extends StatelessWidget {
  const _FormatA({required this.post, required this.onVote, required this.onOpen, this.vote});
  final Post post;
  final bool? vote;
  final PostVote onVote;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _PostHeader(post: post),
          const SizedBox(height: 10),
          Text(post.headline, style: AppText.display(16).copyWith(color: c.textPrimary, height: 1.3)),
          const SizedBox(height: 8),
          _Thumb(post: post, onTap: onOpen),
          const SizedBox(height: 10),
          GestureDetector(
            onTap: onOpen,
            child: Text(post.body, maxLines: 3, overflow: TextOverflow.ellipsis,
                style: AppText.serif(size: 14).copyWith(color: c.textPrimary)),
          ),
          TextButton(
            style: TextButton.styleFrom(padding: EdgeInsets.zero, minimumSize: const Size(0, 28), alignment: Alignment.centerLeft),
            onPressed: onOpen,
            child: Text('Show more', style: AppText.sm.copyWith(color: c.accentPrimary)),
          ),
          _Actions(post: post, vote: vote, onVote: onVote, onOpen: onOpen, withRead: true),
        ],
      ),
    );
  }
}

class _FormatC extends StatelessWidget {
  const _FormatC({required this.post, required this.onVote, required this.onOpen, this.vote});
  final Post post;
  final bool? vote;
  final PostVote onVote;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _PostHeader(post: post),
          const SizedBox(height: 10),
          Text(post.headline, style: AppText.display(16).copyWith(color: c.textPrimary, height: 1.3)),
          const SizedBox(height: 8),
          GestureDetector(
            onTap: onOpen,
            child: Text(post.body, maxLines: 3, overflow: TextOverflow.ellipsis,
                style: AppText.serif(size: 14).copyWith(color: c.textPrimary)),
          ),
          const SizedBox(height: 12),
          SourceCard(
            host: post.linkHost ?? 'source',
            title: post.headline,
            seedName: post.creatorName,
            url: post.linkUrl,
          ),
          _Actions(post: post, vote: vote, onVote: onVote, onOpen: onOpen, openLabel: 'Open source'),
        ],
      ),
    );
  }
}

/// Format B — text-only, tone-tinted, the Lora body is the hero.
class FormatBCard extends StatelessWidget {
  /// Creates a Format-B card. [compact] is used in paired duo rows.
  const FormatBCard({
    super.key,
    required this.post,
    required this.onVote,
    required this.onOpen,
    this.vote,
    this.compact = false,
  });

  final Post post;
  final bool? vote;
  final PostVote onVote;
  final VoidCallback onOpen;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _toneTint(context, post.tone),
        borderRadius: BorderRadius.circular(AppDimens.cardRadius),
        border: Border.all(color: c.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              if (post.tone != null) TonePill(tone: post.tone!) else const SizedBox.shrink(),
              ScoreText(score: post.score),
            ],
          ),
          const SizedBox(height: 12),
          GestureDetector(
            onTap: onOpen,
            child: Text(
              post.body,
              maxLines: compact ? 4 : 2,
              overflow: TextOverflow.ellipsis,
              style: AppText.serif(size: compact ? 15 : 16).copyWith(color: c.textPrimary),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              CreatorAvatar(name: post.creatorName, imageUrl: post.creatorAvatar, size: 24),
              const SizedBox(width: 8),
              Expanded(
                child: Text('${post.creatorName.split(' ').first} · ${_age(post)}',
                    maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: AppText.xs.copyWith(color: c.textTertiary)),
              ),
              _IconVote(icon: Icons.arrow_upward, on: vote == true, color: c.success, onTap: () => onVote(post, true)),
              _IconVote(icon: Icons.arrow_downward, on: vote == false, color: c.danger, onTap: () => onVote(post, false)),
              if (!compact) _IconVote(icon: Icons.north_east, on: false, color: c.accentPrimary, onTap: onOpen),
            ],
          ),
        ],
      ),
    );
  }
}

class _PostHeader extends StatelessWidget {
  const _PostHeader({required this.post});
  final Post post;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        CreatorAvatar(name: post.creatorName, imageUrl: post.creatorAvatar, size: 32),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(post.creatorName, style: AppText.md.copyWith(color: c.textPrimary)),
              Text('@${post.creatorSlug} · ${_age(post)}', style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
            ],
          ),
        ),
        const SizedBox(width: 8),
        if (post.tone != null) TonePill(tone: post.tone!),
        const SizedBox(width: 8),
        ScoreText(score: post.score),
      ],
    );
  }
}

class _Thumb extends StatelessWidget {
  const _Thumb({required this.post, required this.onTap});
  final Post post;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final hasImage = post.imageUrl != null && post.imageUrl!.isNotEmpty;
    return GestureDetector(
      onTap: onTap,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: AspectRatio(
          aspectRatio: 16 / 9,
          child: hasImage
              ? CachedNetworkImage(
                  imageUrl: post.imageUrl!,
                  fit: BoxFit.cover,
                  placeholder: (_, __) => DecoratedBox(decoration: Seeded.thumb(post.creatorName, c.backgroundRaised)),
                  errorWidget: (_, __, ___) => DecoratedBox(decoration: Seeded.thumb(post.creatorName, c.backgroundRaised)),
                )
              : DecoratedBox(decoration: Seeded.thumb(post.creatorName, c.backgroundRaised)),
        ),
      ),
    );
  }
}

class _Actions extends StatelessWidget {
  const _Actions({
    required this.post,
    required this.onVote,
    required this.onOpen,
    this.vote,
    this.withRead = false,
    this.openLabel = 'Open',
  });
  final Post post;
  final bool? vote;
  final PostVote onVote;
  final VoidCallback onOpen;
  final bool withRead;
  final String openLabel;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Row(
        children: [
          VoteButton(icon: Icons.arrow_upward, label: 'Like', color: c.success, active: vote == true, onTap: () => onVote(post, true)),
          const SizedBox(width: 6),
          VoteButton(icon: Icons.arrow_downward, label: 'Dislike', color: c.danger, active: vote == false, onTap: () => onVote(post, false)),
          const SizedBox(width: 6),
          Flexible(child: VoteButton(icon: Icons.north_east, label: openLabel, color: c.accentPrimary, onTap: onOpen)),
          if (withRead) ...[
            const Spacer(),
            Text('${post.readMinutes} min read', style: AppText.mono(size: 11).copyWith(color: c.textTertiary)),
          ],
        ],
      ),
    );
  }
}

class _IconVote extends StatelessWidget {
  const _IconVote({required this.icon, required this.on, required this.color, required this.onTap});
  final IconData icon;
  final bool on;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return IconButton(
      visualDensity: VisualDensity.compact,
      iconSize: 16,
      onPressed: onTap,
      icon: Icon(icon, color: on ? color : c.textSecondary),
    );
  }
}

/// Format-B background tint derived from the post's tone.
Color _toneTint(BuildContext context, String? tone) {
  final c = context.c;
  final surface = c.backgroundSurface;
  return switch (tone?.toLowerCase()) {
    'satirical' => Color.alphaBlend(c.brainAmberSurface.withValues(alpha: 0.7), surface),
    'critical' => Color.alphaBlend(c.danger.withValues(alpha: 0.06), surface),
    'supportive' => Color.alphaBlend(c.success.withValues(alpha: 0.06), surface),
    'informative' => Color.alphaBlend(c.accentSurface.withValues(alpha: 0.6), surface),
    _ => Color.alphaBlend(c.accentSurface.withValues(alpha: 0.6), surface),
  };
}

/// Coarse relative age label for editorial meta lines.
String _age(Post p) {
  final dt = p.createdAt;
  if (dt == null) return 'recently';
  final h = DateTime.now().difference(dt).inHours;
  if (h < 1) return 'just now';
  if (h < 24) return '${h}h ago';
  return '${(h / 24).floor()}d ago';
}
