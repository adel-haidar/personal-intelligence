import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Encrypted persistence for the platform JWT and the small identity fields the
/// app shows before `/auth/me` returns.
///
/// Backed by the Keychain on iOS and EncryptedSharedPreferences on Android.
/// The backend issues a single 7-day JWT (no refresh token), so only
/// [accessToken] is a real session credential — it is also passed to the Open
/// Wearables SDK as its API key.
class TokenStorage {
  /// Creates a [TokenStorage] over flutter_secure_storage.
  TokenStorage([FlutterSecureStorage? storage])
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
            );

  final FlutterSecureStorage _storage;

  static const _kAccessToken = 'access_token';
  static const _kUserId = 'user_id';
  static const _kDisplayName = 'display_name';

  /// Reads the stored JWT, or null if signed out.
  Future<String?> readToken() => _storage.read(key: _kAccessToken);

  /// The cached user id (UUID) of the signed-in account.
  Future<String?> readUserId() => _storage.read(key: _kUserId);

  /// The cached display name, for greeting the user before `/auth/me` loads.
  Future<String?> readDisplayName() => _storage.read(key: _kDisplayName);

  /// Persists a freshly-issued session.
  Future<void> save({required String token, String? userId, String? displayName}) async {
    await _storage.write(key: _kAccessToken, value: token);
    if (userId != null) await _storage.write(key: _kUserId, value: userId);
    if (displayName != null) await _storage.write(key: _kDisplayName, value: displayName);
  }

  /// Clears the session (explicit sign-out or unrecoverable 401).
  Future<void> clear() async {
    await _storage.delete(key: _kAccessToken);
    await _storage.delete(key: _kUserId);
    await _storage.delete(key: _kDisplayName);
  }
}
