import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../theme/app_text_styles.dart';
import '../utils/seeded.dart';

/// A circular creator avatar: the network image if present, otherwise a
/// seeded-colour fill with white Plus Jakarta initials at 40% of the diameter.
class CreatorAvatar extends StatelessWidget {
  /// Creates an avatar for [name] at [size] px.
  const CreatorAvatar({super.key, required this.name, this.imageUrl, this.size = 32});

  final String name;
  final String? imageUrl;
  final double size;

  @override
  Widget build(BuildContext context) {
    final seed = Seeded.color(name);
    final hasImage = imageUrl != null && imageUrl!.isNotEmpty;
    return Container(
      width: size,
      height: size,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(color: seed, shape: BoxShape.circle),
      child: hasImage
          ? CachedNetworkImage(
              imageUrl: imageUrl!,
              fit: BoxFit.cover,
              errorWidget: (_, __, ___) => _initials(),
            )
          : _initials(),
    );
  }

  Widget _initials() => Center(
        child: Text(
          Seeded.initials(name),
          style: AppText.display(size * 0.4).copyWith(color: Colors.white, height: 1),
        ),
      );
}
