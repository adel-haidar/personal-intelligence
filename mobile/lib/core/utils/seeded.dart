import 'package:flutter/material.dart';

/// Seeded per-creator identity for the editorial PULSE/SIGNAL surfaces.
///
/// Each creator name hashes to a stable colour from a fixed palette, so the
/// same voice always reads with the same colour (avatar fill + thumbnail tint).
class Seeded {
  Seeded._();

  /// The cycling seed palette (matches the design handoff exactly).
  static const palette = <Color>[
    Color(0xFF4F46E5),
    Color(0xFF0891B2),
    Color(0xFF0D9488),
    Color(0xFFB45309),
    Color(0xFF7C3AED),
    Color(0xFFBE185D),
  ];

  /// Stable 32-bit string hash (same algorithm as the prototype's `feedHash`).
  static int _hash(String s) {
    var h = 0;
    for (var i = 0; i < s.length; i++) {
      h = (h * 31 + s.codeUnitAt(i)) & 0xFFFFFFFF;
    }
    return h;
  }

  /// The consistent colour for [name].
  static Color color(String name) => palette[_hash(name.isEmpty ? '?' : name) % palette.length];

  /// Up to two uppercase initials for an avatar.
  static String initials(String name) {
    final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
    if (parts.isEmpty) return '?';
    if (parts.length == 1) return parts.first.characters.first.toUpperCase();
    return (parts.first.characters.first + parts.last.characters.first).toUpperCase();
  }

  /// A subtle tinted backdrop for a thumbnail/hero derived from the seed,
  /// blending into [raised] (the surface's `background.raised`).
  static BoxDecoration thumb(String name, Color raised) {
    final c = color(name);
    return BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color.alphaBlend(c.withValues(alpha: 0.28), raised), raised],
      ),
    );
  }
}
