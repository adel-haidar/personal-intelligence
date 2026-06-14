import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// The signature Calm Intelligence element: four amber dots orbiting a centre
/// point at different radii and periods.
///
/// * [size] — 16 (nav), 32 (dashboard), 48 (brain hero).
/// * [isStatic] — when the brain organiser is running, render 💤 instead.
/// * Respects reduced motion: if [respectReducedMotion] and the platform has
///   `disableAnimations`, the dots are drawn in their start positions, frozen.
class BrainPulse extends StatefulWidget {
  /// Creates a Brain Pulse of the given [size].
  const BrainPulse({
    super.key,
    required this.size,
    this.isStatic = false,
    this.slow = false,
    this.respectReducedMotion = true,
  });

  /// Diameter in logical pixels.
  final double size;

  /// When true the organiser is running — show a sleeping indicator.
  final bool isStatic;

  /// When true the orbits run at half speed (the "no memories yet" nav state).
  final bool slow;

  /// Whether to freeze when the OS requests reduced motion.
  final bool respectReducedMotion;

  @override
  State<BrainPulse> createState() => _BrainPulseState();
}

class _BrainPulseState extends State<BrainPulse> with SingleTickerProviderStateMixin {
  // 120s is divisible by every dot period (8/12/10/15) for a seamless loop;
  // 240s (slow) keeps the same divisibility at half speed.
  int get _loopSeconds => widget.slow ? 240 : 120;
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: Duration(seconds: _loopSeconds));

  // (radiusFraction, periodSeconds, startDegrees) per the spec.
  static const _orbits = <List<double>>[
    [0.30, 8, 0],
    [0.45, 12, 90],
    [0.35, 10, 200],
    [0.55, 15, 310],
  ];

  @override
  void initState() {
    super.initState();
    _controller.repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.isStatic) {
      return SizedBox(
        width: widget.size,
        height: widget.size,
        child: Center(
          child: Text('💤', style: TextStyle(fontSize: widget.size * 0.6)),
        ),
      );
    }

    final reduceMotion = widget.respectReducedMotion && MediaQuery.of(context).disableAnimations;
    final amber = context.c.brainAmber;

    if (reduceMotion) {
      return CustomPaint(
        size: Size.square(widget.size),
        painter: _BrainPulsePainter(elapsed: 0, color: amber),
      );
    }

    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) => CustomPaint(
        size: Size.square(widget.size),
        painter: _BrainPulsePainter(elapsed: _controller.value * _loopSeconds, color: amber),
      ),
    );
  }
}

class _BrainPulsePainter extends CustomPainter {
  _BrainPulsePainter({required this.elapsed, required this.color});

  /// Elapsed time in seconds within the 120s loop.
  final double elapsed;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final centre = Offset(size.width / 2, size.height / 2);
    final dotRadius = (size.width * 0.08).clamp(1.2, 6.0);

    // Centre anchor dot.
    canvas.drawCircle(centre, dotRadius * 0.8, Paint()..color = color.withValues(alpha: 0.35));

    for (final orbit in _BrainPulseState._orbits) {
      final radius = size.width / 2 * orbit[0];
      final period = orbit[1];
      final startRad = orbit[2] * math.pi / 180;
      final angle = startRad + (elapsed / period) * 2 * math.pi;
      final pos = centre + Offset(math.cos(angle) * radius, math.sin(angle) * radius);
      canvas.drawCircle(pos, dotRadius, Paint()..color = color);
    }
  }

  @override
  bool shouldRepaint(_BrainPulsePainter old) => old.elapsed != elapsed || old.color != color;
}
