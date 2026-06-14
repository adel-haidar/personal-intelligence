import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/login_screen.dart';
import '../../features/auth/register_screen.dart';
import '../../features/brain/brain_screen.dart';
import '../../features/brain/memory_detail_screen.dart';
import '../../features/dashboard/dashboard_screen.dart';
import '../../features/finances/finances_screen.dart';
import '../../features/health/health_screen.dart';
import '../../features/health/health_callback_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/pulse/pulse_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/shell/home_shell.dart';
import '../../features/signal/signal_screen.dart';
import '../../features/signal/video_player_screen.dart';
import '../../features/stories/stories_library_screen.dart';
import '../../features/stories/film_detail_screen.dart';
import '../../features/stories/series_screen.dart';
import '../../features/stories/stories_player_screen.dart';
import '../../features/stories/stories_category_screen.dart';
import '../../features/stories/stories_search_screen.dart';
import '../../features/aria/aria_library_screen.dart';
import '../../features/aria/now_playing_screen.dart';
import '../../features/aria/playlist_detail_screen.dart';
import '../../features/aria/aria_search_screen.dart';
import '../../providers/auth_provider.dart';

/// Route path constants — used across the app instead of string literals.
class Routes {
  Routes._();
  static const login = '/login';
  static const register = '/register';
  static const onboarding = '/onboarding';
  static const dashboard = '/dashboard';
  static const brain = '/brain';
  static const pulse = '/pulse';
  static const health = '/health';
  static const signal = '/signal';
  static const finances = '/finances';
  static const settings = '/settings';
  static const healthCallback = '/health/devices/callback';
  static const stories = '/stories';
  static const storiesPlayer = '/stories/player';
  static const storiesSearch = '/stories/search';
  static const storiesCategory = '/stories/category';
  static const aria = '/aria';
  static const ariaNow = '/aria/now';
  static const ariaSearch = '/aria/search';
}

final _rootKey = GlobalKey<NavigatorState>();
final _shellKey = GlobalKey<NavigatorState>();

/// The app router, with an auth guard driven by [authControllerProvider].
final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    navigatorKey: _rootKey,
    initialLocation: Routes.dashboard,
    refreshListenable: _AuthListenable(ref),
    redirect: (context, state) {
      final auth = ref.read(authControllerProvider);
      final loc = state.matchedLocation;
      const publicRoutes = {Routes.login, Routes.register, Routes.onboarding, Routes.healthCallback};
      final isPublic = publicRoutes.contains(loc);

      // Still resolving the stored token — don't bounce yet.
      if (auth is AuthLoading) return null;

      if (auth is AuthSignedOut) return isPublic ? null : Routes.login;

      if (auth is AuthSignedIn) {
        if (auth.needsOnboarding && loc != Routes.onboarding) return Routes.onboarding;
        // Signed in and on an auth page → go home.
        if (loc == Routes.login || loc == Routes.register) return Routes.dashboard;
      }
      return null;
    },
    routes: [
      GoRoute(path: Routes.login, builder: (_, __) => const LoginScreen()),
      GoRoute(path: Routes.register, builder: (_, __) => const RegisterScreen()),
      GoRoute(path: Routes.onboarding, builder: (_, __) => const OnboardingScreen()),
      GoRoute(
        path: Routes.healthCallback,
        builder: (_, state) => HealthCallbackScreen(query: state.uri.queryParameters),
      ),

      // Full-screen routes pushed over the shell.
      GoRoute(
        path: Routes.signal,
        parentNavigatorKey: _rootKey,
        builder: (_, __) => const SignalScreen(),
      ),
      GoRoute(
        path: '/signal/video/:id',
        parentNavigatorKey: _rootKey,
        builder: (_, state) => VideoPlayerScreen(videoId: state.pathParameters['id']!),
      ),
      GoRoute(
        path: Routes.finances,
        parentNavigatorKey: _rootKey,
        builder: (_, __) => const FinancesScreen(),
      ),
      GoRoute(
        path: Routes.settings,
        parentNavigatorKey: _rootKey,
        builder: (_, __) => const SettingsScreen(),
      ),
      GoRoute(
        path: '/brain/memory/:id',
        parentNavigatorKey: _rootKey,
        builder: (_, state) => MemoryDetailScreen(memoryId: state.pathParameters['id']!),
      ),

      // STORIES (long-form cinema) — all full-screen pushed routes.
      GoRoute(path: Routes.stories, parentNavigatorKey: _rootKey, builder: (_, __) => const StoriesLibraryScreen()),
      GoRoute(path: Routes.storiesSearch, parentNavigatorKey: _rootKey, builder: (_, __) => const StoriesSearchScreen()),
      GoRoute(
        path: Routes.storiesCategory,
        parentNavigatorKey: _rootKey,
        builder: (_, state) => StoriesCategoryScreen(category: state.uri.queryParameters['cat'] ?? 'All'),
      ),
      GoRoute(
        path: Routes.storiesPlayer,
        parentNavigatorKey: _rootKey,
        builder: (_, state) {
          final q = state.uri.queryParameters;
          return StoriesPlayerScreen(
            filmId: q['film'],
            seriesId: q['series'],
            episodeNumber: int.tryParse(q['ep'] ?? ''),
            episodeId: q['episode'],
          );
        },
      ),
      GoRoute(
        path: '/stories/film/:id',
        parentNavigatorKey: _rootKey,
        builder: (_, state) => FilmDetailScreen(filmId: state.pathParameters['id']!),
      ),
      GoRoute(
        path: '/stories/series/:id',
        parentNavigatorKey: _rootKey,
        builder: (_, state) => SeriesScreen(seriesId: state.pathParameters['id']!),
      ),

      // ARIA (AI music) — full-screen pushed routes (the mini-player lives in the shell).
      GoRoute(path: Routes.aria, parentNavigatorKey: _rootKey, builder: (_, __) => const AriaLibraryScreen()),
      GoRoute(path: Routes.ariaNow, parentNavigatorKey: _rootKey, builder: (_, __) => const NowPlayingScreen()),
      GoRoute(path: Routes.ariaSearch, parentNavigatorKey: _rootKey, builder: (_, __) => const AriaSearchScreen()),
      GoRoute(
        path: '/aria/playlist/:id',
        parentNavigatorKey: _rootKey,
        builder: (_, state) => PlaylistDetailScreen(playlistId: state.pathParameters['id']!),
      ),

      // Bottom-nav shell (Dashboard / Brain / Pulse / Health).
      ShellRoute(
        navigatorKey: _shellKey,
        builder: (_, __, child) => HomeShell(child: child),
        routes: [
          GoRoute(path: Routes.dashboard, builder: (_, __) => const DashboardScreen()),
          GoRoute(path: Routes.brain, builder: (_, __) => const BrainScreen()),
          GoRoute(path: Routes.pulse, builder: (_, __) => const PulseScreen()),
          GoRoute(path: Routes.health, builder: (_, __) => const HealthScreen()),
        ],
      ),
    ],
  );
});

/// Bridges Riverpod [authControllerProvider] changes to GoRouter's
/// [Listenable]-based refresh.
class _AuthListenable extends ChangeNotifier {
  _AuthListenable(Ref ref) {
    ref.listen(authControllerProvider, (_, __) => notifyListeners());
  }
}
