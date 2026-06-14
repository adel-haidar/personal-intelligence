import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/models/user.dart';
import 'core_providers.dart';

/// High-level authentication state for the router guard and UI.
sealed class AuthState {
  const AuthState();
}

/// Still resolving the stored token at startup.
class AuthLoading extends AuthState {
  const AuthLoading();
}

/// No valid session.
class AuthSignedOut extends AuthState {
  const AuthSignedOut();
}

/// Signed in; [user] is null until `/auth/me` resolves but the token is valid.
class AuthSignedIn extends AuthState {
  /// Wraps the (possibly not-yet-loaded) [user].
  const AuthSignedIn(this.user);
  final AppUser? user;

  /// Whether onboarding still needs completing.
  bool get needsOnboarding => user != null && !user!.onboardingCompleted;
}

/// Owns sign-in/out and the cached current user.
class AuthController extends Notifier<AuthState> {
  @override
  AuthState build() {
    // React to interceptor-driven 401s by signing out.
    ref.listen(unauthorizedSignalProvider, (_, __) => _forceSignOut());
    _bootstrap();
    return const AuthLoading();
  }

  Future<void> _bootstrap() async {
    final repo = ref.read(authRepositoryProvider);
    final token = await repo.currentToken();
    if (token == null || token.isEmpty) {
      state = const AuthSignedOut();
      return;
    }
    // Token present — optimistically signed in, then verify in the background.
    state = const AuthSignedIn(null);
    try {
      final user = await repo.me();
      state = AuthSignedIn(user);
    } catch (_) {
      // Network hiccup: stay optimistically signed in. A real 401 is handled by
      // the interceptor via [unauthorizedSignalProvider].
    }
  }

  /// Signs in with email + password.
  Future<void> login({required String email, required String password}) async {
    final user = await ref.read(authRepositoryProvider).login(email: email, password: password);
    state = AuthSignedIn(user);
  }

  /// Re-fetches `/auth/me` (e.g. after editing the profile or onboarding).
  Future<void> refreshUser() async {
    if (state is! AuthSignedIn) return;
    try {
      state = AuthSignedIn(await ref.read(authRepositoryProvider).me());
    } catch (_) {/* keep last known user */}
  }

  /// Replaces the cached user locally (after a profile PATCH echoes the row).
  void setUser(AppUser user) => state = AuthSignedIn(user);

  /// Explicit sign-out from Settings.
  Future<void> logout() async {
    await ref.read(authRepositoryProvider).logout();
    state = const AuthSignedOut();
  }

  Future<void> _forceSignOut() async {
    await ref.read(authRepositoryProvider).logout();
    state = const AuthSignedOut();
  }
}

/// The app-wide auth controller.
final authControllerProvider = NotifierProvider<AuthController, AuthState>(AuthController.new);
