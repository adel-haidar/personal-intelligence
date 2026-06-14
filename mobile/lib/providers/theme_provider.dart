import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core_providers.dart';

/// Persists and exposes the [ThemeMode]. Dark is the product default.
class ThemeController extends Notifier<ThemeMode> {
  static const _key = 'theme_mode';

  @override
  ThemeMode build() {
    final prefs = ref.watch(sharedPreferencesProvider);
    switch (prefs.getString(_key)) {
      case 'light':
        return ThemeMode.light;
      case 'system':
        return ThemeMode.system;
      case 'dark':
        return ThemeMode.dark;
      default:
        return ThemeMode.dark; // default: dark
    }
  }

  /// Sets and persists the theme mode (light / dark / system).
  Future<void> set(ThemeMode mode) async {
    state = mode;
    final value = switch (mode) {
      ThemeMode.light => 'light',
      ThemeMode.system => 'system',
      ThemeMode.dark => 'dark',
    };
    await ref.read(sharedPreferencesProvider).setString(_key, value);
  }

  /// Flips between light and dark.
  Future<void> toggle() => set(state == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark);
}

/// The active theme mode.
final themeControllerProvider = NotifierProvider<ThemeController, ThemeMode>(ThemeController.new);
