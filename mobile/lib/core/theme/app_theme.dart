import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'app_colors.dart';
import 'app_dimens.dart';
import 'app_text_styles.dart';

/// Builds the light and dark [ThemeData] for Calm Intelligence.
///
/// Cards/surfaces carry no shadow (elevation 0); depth is conveyed by the
/// background-colour steps defined in [AppPalette]. Only sheets and dialogs use
/// elevation.
class AppTheme {
  AppTheme._();

  /// The light theme.
  static ThemeData get light => _build(AppPalette.light);

  /// The dark theme (product default).
  static ThemeData get dark => _build(AppPalette.dark);

  static ThemeData _build(AppPalette p) {
    final base = p.isDark ? ThemeData.dark(useMaterial3: true) : ThemeData.light(useMaterial3: true);
    final scheme = ColorScheme.fromSeed(
      seedColor: p.accentPrimary,
      brightness: p.isDark ? Brightness.dark : Brightness.light,
    ).copyWith(
      primary: p.accentPrimary,
      surface: p.backgroundSurface,
      error: p.danger,
      onSurface: p.textPrimary,
    );

    return base.copyWith(
      scaffoldBackgroundColor: p.backgroundPage,
      colorScheme: scheme,
      canvasColor: p.backgroundPage,
      dividerColor: p.borderSubtle,
      // Calm Intelligence motion: page transitions are a 150ms fade everywhere.
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: _FadePageTransitionsBuilder(),
          TargetPlatform.iOS: _FadePageTransitionsBuilder(),
          TargetPlatform.macOS: _FadePageTransitionsBuilder(),
        },
      ),
      textTheme: GoogleFonts.interTextTheme(base.textTheme).apply(
        bodyColor: p.textPrimary,
        displayColor: p.textPrimary,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: p.backgroundPage,
        foregroundColor: p.textPrimary,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: AppText.md.copyWith(color: p.textPrimary),
      ),
      cardTheme: CardThemeData(
        color: p.backgroundSurface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimens.cardRadius),
          side: BorderSide(color: p.borderSubtle),
        ),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: p.backgroundSurface,
        elevation: AppDimens.sheetElevation,
        modalElevation: AppDimens.sheetElevation,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(AppDimens.modalRadius)),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: p.backgroundSurface,
        elevation: AppDimens.sheetElevation,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppDimens.modalRadius)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: p.backgroundInput,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppDimens.space4,
          vertical: AppDimens.space3,
        ),
        hintStyle: AppText.base.copyWith(color: p.textTertiary),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppDimens.inputRadius),
          borderSide: BorderSide(color: p.borderMedium),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppDimens.inputRadius),
          borderSide: BorderSide(color: p.borderSubtle),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppDimens.inputRadius),
          borderSide: BorderSide(color: p.accentPrimary, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppDimens.inputRadius),
          borderSide: BorderSide(color: p.danger),
        ),
      ),
      chipTheme: base.chipTheme.copyWith(
        backgroundColor: p.backgroundRaised,
        side: BorderSide(color: p.borderSubtle),
        labelStyle: AppText.sm.copyWith(color: p.textSecondary),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppDimens.pillRadius)),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: p.brainAmber,
        linearTrackColor: p.backgroundRaised,
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: p.backgroundRaised,
        contentTextStyle: AppText.sm.copyWith(color: p.textPrimary),
        elevation: AppDimens.sheetElevation,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppDimens.inputRadius)),
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? p.accentPrimary : p.textTertiary,
        ),
        trackColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? p.accentSurface : p.backgroundRaised,
        ),
      ),
    );
  }
}

/// A page transition that simply cross-fades over 150ms — no slide, no zoom.
/// Used app-wide so GoRouter's `MaterialPage` routes fade in/out.
class _FadePageTransitionsBuilder extends PageTransitionsBuilder {
  const _FadePageTransitionsBuilder();

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) {
    return FadeTransition(opacity: animation, child: child);
  }
}
