import 'package:flutter/material.dart';

/// Calm Intelligence colour tokens — mirrors `frontend/src/styles/tokens.css`.
///
/// Two palettes (light/dark) exposed as raw [Color] constants. Theme wiring
/// lives in [AppTheme]; widgets should prefer reading from `Theme.of(context)`
/// or [AppColorsX] (the `context.c` extension) rather than these constants
/// directly, so dark mode resolves automatically.
class AppColors {
  AppColors._();

  // ---- Light mode -------------------------------------------------------
  static const backgroundPage = Color(0xFFF8F7F4);
  static const backgroundSurface = Color(0xFFFFFFFF);
  static const backgroundRaised = Color(0xFFF2F1EE);
  static const backgroundInput = Color(0xFFFAFAF8);
  static const textPrimary = Color(0xFF1C1B2E);
  static const textSecondary = Color(0xFF5A5970);
  static const textTertiary = Color(0xFF9896A8);
  static const accentPrimary = Color(0xFF5B5BD6);
  static const accentHover = Color(0xFF4A4ABE);
  static const accentSurface = Color(0xFFEEECFF);
  static const brainAmber = Color(0xFFE8A444);
  static const brainAmberSurface = Color(0xFFFEF3E0);
  static const borderSubtle = Color(0xFFE8E6E0);
  static const borderMedium = Color(0xFFD4D1C8);
  static const success = Color(0xFF2D7A4F);
  static const warning = Color(0xFFB45309);
  static const danger = Color(0xFFC0392B);
  static const info = Color(0xFF2563EB);
  // Derived status / tone surfaces (light).
  static const successSurface = Color(0xFFE4F2EA);
  static const dangerSurface = Color(0xFFFBE9E7);
  static const warningSurface = Color(0xFFFCEFD9);

  // ---- Dark mode --------------------------------------------------------
  static const darkBackgroundPage = Color(0xFF0C0C14);
  static const darkBackgroundSurface = Color(0xFF13131E);
  static const darkBackgroundRaised = Color(0xFF1A1A28);
  static const darkBackgroundInput = Color(0xFF0F0F1A);
  static const darkTextPrimary = Color(0xFFE4E4F0);
  static const darkTextSecondary = Color(0xFF9090AA);
  static const darkTextTertiary = Color(0xFF5A5A70);
  static const darkAccentPrimary = Color(0xFF7C7EE0);
  static const darkAccentHover = Color(0xFF9092E8);
  static const darkAccentSurface = Color(0xFF1E1E38);
  static const darkBrainAmber = Color(0xFFD4923A);
  static const darkBrainAmberSurface = Color(0xFF221A0C);
  static const darkBorderSubtle = Color(0xFF1E1E2E);
  static const darkBorderMedium = Color(0xFF282838);
  static const darkSuccess = Color(0xFF34D399);
  static const darkWarning = Color(0xFFFBBF24);
  static const darkDanger = Color(0xFFF87171);
  static const darkInfo = Color(0xFF60A5FA);
  // Derived status / tone surfaces (dark).
  static const darkSuccessSurface = Color(0xFF102A1E);
  static const darkDangerSurface = Color(0xFF2A1413);
  static const darkWarningSurface = Color(0xFF2A2008);
}

/// Resolved semantic palette for a single brightness. Widgets read these via
/// `context.c` so the right value is picked for the active [ThemeMode].
class AppPalette {
  /// Builds the palette for the given [brightness].
  const AppPalette({
    required this.backgroundPage,
    required this.backgroundSurface,
    required this.backgroundRaised,
    required this.backgroundInput,
    required this.textPrimary,
    required this.textSecondary,
    required this.textTertiary,
    required this.accentPrimary,
    required this.accentHover,
    required this.accentSurface,
    required this.brainAmber,
    required this.brainAmberSurface,
    required this.borderSubtle,
    required this.borderMedium,
    required this.success,
    required this.warning,
    required this.danger,
    required this.info,
    required this.successSurface,
    required this.dangerSurface,
    required this.warningSurface,
    required this.isDark,
  });

  final Color backgroundPage;
  final Color backgroundSurface;
  final Color backgroundRaised;
  final Color backgroundInput;
  final Color textPrimary;
  final Color textSecondary;
  final Color textTertiary;
  final Color accentPrimary;
  final Color accentHover;
  final Color accentSurface;
  final Color brainAmber;
  final Color brainAmberSurface;
  final Color borderSubtle;
  final Color borderMedium;
  final Color success;
  final Color warning;
  final Color danger;
  final Color info;
  final Color successSurface;
  final Color dangerSurface;
  final Color warningSurface;
  final bool isDark;

  /// The light Calm Intelligence palette.
  static const light = AppPalette(
    backgroundPage: AppColors.backgroundPage,
    backgroundSurface: AppColors.backgroundSurface,
    backgroundRaised: AppColors.backgroundRaised,
    backgroundInput: AppColors.backgroundInput,
    textPrimary: AppColors.textPrimary,
    textSecondary: AppColors.textSecondary,
    textTertiary: AppColors.textTertiary,
    accentPrimary: AppColors.accentPrimary,
    accentHover: AppColors.accentHover,
    accentSurface: AppColors.accentSurface,
    brainAmber: AppColors.brainAmber,
    brainAmberSurface: AppColors.brainAmberSurface,
    borderSubtle: AppColors.borderSubtle,
    borderMedium: AppColors.borderMedium,
    success: AppColors.success,
    warning: AppColors.warning,
    danger: AppColors.danger,
    info: AppColors.info,
    successSurface: AppColors.successSurface,
    dangerSurface: AppColors.dangerSurface,
    warningSurface: AppColors.warningSurface,
    isDark: false,
  );

  /// The dark Calm Intelligence palette (the product default).
  static const dark = AppPalette(
    backgroundPage: AppColors.darkBackgroundPage,
    backgroundSurface: AppColors.darkBackgroundSurface,
    backgroundRaised: AppColors.darkBackgroundRaised,
    backgroundInput: AppColors.darkBackgroundInput,
    textPrimary: AppColors.darkTextPrimary,
    textSecondary: AppColors.darkTextSecondary,
    textTertiary: AppColors.darkTextTertiary,
    accentPrimary: AppColors.darkAccentPrimary,
    accentHover: AppColors.darkAccentHover,
    accentSurface: AppColors.darkAccentSurface,
    brainAmber: AppColors.darkBrainAmber,
    brainAmberSurface: AppColors.darkBrainAmberSurface,
    borderSubtle: AppColors.darkBorderSubtle,
    borderMedium: AppColors.darkBorderMedium,
    success: AppColors.darkSuccess,
    warning: AppColors.darkWarning,
    danger: AppColors.darkDanger,
    info: AppColors.darkInfo,
    successSurface: AppColors.darkSuccessSurface,
    dangerSurface: AppColors.darkDangerSurface,
    warningSurface: AppColors.darkWarningSurface,
    isDark: true,
  );
}

/// Convenient palette lookup: `context.c.brainAmber`.
extension AppColorsX on BuildContext {
  /// The resolved [AppPalette] for the active brightness.
  AppPalette get c =>
      Theme.of(this).brightness == Brightness.dark ? AppPalette.dark : AppPalette.light;
}
