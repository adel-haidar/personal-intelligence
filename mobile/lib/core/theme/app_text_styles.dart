import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Typography for Calm Intelligence.
///
/// Web → Flutter font mapping:
/// * Plus Jakarta Sans — headings, nav labels, button text
/// * Inter — body text, UI labels, descriptions
/// * Lora — memory content, brain intro, health/finance insight cards
/// * JetBrains Mono — numeric data, timestamps, file sizes, memory counts
///
/// The type scale matches the web exactly (see task spec). `color` is applied
/// by the caller / theme so the same style works in light and dark.
class AppText {
  AppText._();

  // ---- Plus Jakarta Sans (display / headings) ---------------------------
  // Mobile scale: lg 20 · xl 26 · 2xl 34. Tracking -0.01em above 20px.
  /// 34px / 600 — onboarding hero titles.
  static TextStyle get xxl => GoogleFonts.plusJakartaSans(
      fontSize: 34, fontWeight: FontWeight.w600, height: 1.15, letterSpacing: -0.34);

  /// 26px / 600 — page heroes, brain title.
  static TextStyle get xl => GoogleFonts.plusJakartaSans(
      fontSize: 26, fontWeight: FontWeight.w600, height: 1.2, letterSpacing: -0.26);

  /// 20px / 600 — section titles, greetings.
  static TextStyle get lg => GoogleFonts.plusJakartaSans(
      fontSize: 20, fontWeight: FontWeight.w600, height: 1.25, letterSpacing: -0.2);

  /// 17px / 500 — subheadings, card titles.
  static TextStyle get md =>
      GoogleFonts.plusJakartaSans(fontSize: 17, fontWeight: FontWeight.w500, height: 1.3);

  /// Plus Jakarta Sans 600 at an arbitrary [size] — wordmarks, big stat values.
  static TextStyle display(double size, {FontWeight weight = FontWeight.w600}) =>
      GoogleFonts.plusJakartaSans(
          fontSize: size,
          fontWeight: weight,
          height: 1.15,
          letterSpacing: size > 20 ? size * -0.01 : 0);

  /// Button / nav label text (Plus Jakarta Sans 600, 15px).
  static TextStyle get button =>
      GoogleFonts.plusJakartaSans(fontSize: 15, fontWeight: FontWeight.w600);

  // ---- Inter (body / UI) ------------------------------------------------
  /// 15px / 400 — body text, post bodies. Line-height 1.65 per the handoff.
  static TextStyle get base => GoogleFonts.inter(fontSize: 15, fontWeight: FontWeight.w400, height: 1.65);

  /// 13px / 400 — captions, helper text.
  static TextStyle get sm => GoogleFonts.inter(fontSize: 13, fontWeight: FontWeight.w400, height: 1.45);

  /// 11px / 400 — timestamps, secondary labels.
  static TextStyle get xs => GoogleFonts.inter(fontSize: 11, fontWeight: FontWeight.w400, height: 1.4);

  /// 12px / 500 — stat labels under big numbers.
  static TextStyle get label =>
      GoogleFonts.inter(fontSize: 12, fontWeight: FontWeight.w500, height: 1.3);

  // ---- Lora (serif — reflective content) --------------------------------
  /// Lora serif body for memory/insight content. [italic] for file-sourced text.
  static TextStyle serif({double size = 17, bool italic = false, FontWeight weight = FontWeight.w400}) =>
      GoogleFonts.lora(
        fontSize: size,
        fontWeight: weight,
        height: 1.55,
        fontStyle: italic ? FontStyle.italic : FontStyle.normal,
      );

  // ---- JetBrains Mono (data) -------------------------------------------
  /// Monospace data label — timestamps, counts, file sizes, scores.
  static TextStyle mono({double size = 11, FontWeight weight = FontWeight.w400}) =>
      GoogleFonts.jetBrainsMono(fontSize: size, fontWeight: weight, letterSpacing: 0.2);
}
