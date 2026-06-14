import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/api/api_client.dart';
import '../core/auth/auth_repository.dart';
import '../core/auth/token_storage.dart';
import '../core/health/health_bg_sync_service.dart';

/// Encrypted token storage singleton.
final tokenStorageProvider = Provider<TokenStorage>((ref) => TokenStorage());

/// Broadcasts unrecoverable 401s so [authControllerProvider] can sign out and
/// the router can redirect. A simple incrementing counter — listeners react to
/// changes rather than to a value.
final unauthorizedSignalProvider = StateProvider<int>((ref) => 0);

/// The shared [ApiClient]. On a 401 it bumps [unauthorizedSignalProvider].
final apiClientProvider = Provider<ApiClient>((ref) {
  final storage = ref.watch(tokenStorageProvider);
  return ApiClient(
    tokenStorage: storage,
    onUnauthorized: () {
      ref.read(unauthorizedSignalProvider.notifier).state++;
    },
  );
});

/// The auth repository.
final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(ref.watch(apiClientProvider), ref.watch(tokenStorageProvider)),
);

/// Open Wearables native background-sync service (currently a safe stub).
final healthBgSyncServiceProvider = Provider<HealthBgSyncService>(
  (ref) => HealthBgSyncService(ref.watch(tokenStorageProvider)),
);

/// SharedPreferences, overridden with the resolved instance in `main()`.
final sharedPreferencesProvider = Provider<SharedPreferences>(
  (ref) => throw UnimplementedError('sharedPreferencesProvider must be overridden in main()'),
);
