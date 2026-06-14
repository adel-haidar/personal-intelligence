import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_dimens.dart';

/// A bordered, shadowless surface — the base container for everything.
///
/// Depth comes from the border + background step, never elevation. Pass
/// [accentBorderColor] to draw a 3px left rule (used by banners/insight cards).
class AppCard extends StatelessWidget {
  /// Creates a card wrapping [child].
  const AppCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(AppDimens.space4),
    this.onTap,
    this.accentBorderColor,
    this.background,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;

  /// When set, a 3px coloured rule is drawn down the leading edge.
  final Color? accentBorderColor;
  final Color? background;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final radius = BorderRadius.circular(AppDimens.cardRadius);
    Widget content = Container(
      decoration: BoxDecoration(
        color: background ?? c.backgroundSurface,
        borderRadius: radius,
        border: Border.all(color: c.borderSubtle),
      ),
      child: ClipRRect(
        borderRadius: radius,
        child: accentBorderColor != null
            ? Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Container(width: 3, color: accentBorderColor),
                  Expanded(child: Padding(padding: padding, child: child)),
                ],
              )
            : Padding(padding: padding, child: child),
      ),
    );

    if (onTap == null) return content;
    return _PressScale(
      onTap: onTap!,
      borderRadius: radius,
      child: content,
    );
  }
}

/// Wraps a child with the standard 80ms scale(0.97) press feedback.
class _PressScale extends StatefulWidget {
  const _PressScale({required this.child, required this.onTap, required this.borderRadius});
  final Widget child;
  final VoidCallback onTap;
  final BorderRadius borderRadius;

  @override
  State<_PressScale> createState() => _PressScaleState();
}

class _PressScaleState extends State<_PressScale> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTapDown: (_) => setState(() => _down = true),
      onTapUp: (_) => setState(() => _down = false),
      onTapCancel: () => setState(() => _down = false),
      onTap: widget.onTap,
      child: AnimatedScale(
        scale: _down ? 0.97 : 1.0,
        duration: const Duration(milliseconds: 80),
        child: widget.child,
      ),
    );
  }
}
