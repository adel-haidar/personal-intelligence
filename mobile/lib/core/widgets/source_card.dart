import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme/app_colors.dart';
import '../theme/app_text_styles.dart';
import '../utils/seeded.dart';

/// An inline, tappable source card (Format C posts + the player's Sources list):
/// a seeded favicon swatch, the domain, and the article title.
class SourceCard extends StatelessWidget {
  /// Creates a source card.
  const SourceCard({super.key, required this.host, required this.title, required this.seedName, this.url});

  final String host;
  final String title;
  final String seedName;
  final String? url;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: url == null ? null : () => launchUrl(Uri.parse(url!), mode: LaunchMode.externalApplication),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: c.backgroundRaised,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: c.borderMedium),
        ),
        child: Row(
          children: [
            Container(
              width: 18,
              height: 18,
              decoration: BoxDecoration(
                color: Seeded.color(seedName),
                borderRadius: BorderRadius.circular(4),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(host, style: AppText.xs.copyWith(color: c.textTertiary)),
                  Text(
                    title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppText.sm.copyWith(color: c.textPrimary, fontWeight: FontWeight.w500),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
