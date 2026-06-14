import '../api/api_endpoints.dart';
import '../auth/token_storage.dart';

/// Thin wrapper around the Open Wearables `health_bg_sync` SDK for native
/// background health sync (Apple Health on iOS, Health Connect on Android).
///
/// The real SDK is not yet a dependency (see pubspec TODO), so this is a
/// compile-safe stub: it exposes the intended surface and reports
/// [isAvailable] == false until the package is wired in. Swap the bodies for
/// real `HealthBgSync.instance` calls once the dependency is added — the call
/// sites in the Health screen don't need to change.
///
/// Background sync posts directly to the Open Wearables ingest host
/// (`/wearables`) using the platform JWT as the API key; it does NOT route
/// through this app's Dio client.
class HealthBgSyncService {
  /// Creates the service over [_tokenStorage].
  HealthBgSyncService(this._tokenStorage);

  final TokenStorage _tokenStorage;

  /// The ingest host the SDK should sync to.
  static String get host => '${ApiEndpoints.baseUrl.replaceFirst('/api', '')}/wearables';

  /// The health data types we request authorization for.
  static const requestedTypes = <String>[
    'heartRate', 'steps', 'sleep', 'workout', 'weight', 'spo2',
  ];

  /// Whether the native SDK is present and usable. Always false until the
  /// `health_bg_sync` dependency is added to pubspec.yaml.
  bool get isAvailable => false;

  /// Configures the SDK with host + credentials, requests authorization for
  /// [requestedTypes], and starts background sync.
  ///
  /// Returns true if sync was started. The stub returns false.
  Future<bool> configureAndStart() async {
    if (!isAvailable) return false;
    // TODO(open-wearables): replace with the real SDK once the dependency exists:
    //   final apiKey = await _tokenStorage.readToken();
    //   final userId = await _tokenStorage.readUserId();
    //   await HealthBgSync.instance.configure(host: host, apiKey: apiKey, userId: userId);
    //   await HealthBgSync.instance.requestAuthorization(requestedTypes);
    //   await HealthBgSync.instance.startBackgroundSync();
    //   return true;
    await _tokenStorage.readToken(); // referenced so the field isn't "unused".
    return false;
  }

  /// Stops background sync (e.g. on sign-out).
  Future<void> stop() async {
    if (!isAvailable) return;
    // TODO(open-wearables): await HealthBgSync.instance.stopBackgroundSync();
  }
}
