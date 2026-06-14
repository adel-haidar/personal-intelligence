import '../api/api_client.dart';
import '../api/api_endpoints.dart';
import '../models/user.dart';
import 'token_storage.dart';

/// Owns the login/register/session lifecycle against `/api/auth/*`.
///
/// The backend returns a single JWT (`{"token", "user"}`) with a 7-day TTL and
/// no refresh token, so "staying signed in" simply means the JWT is still valid;
/// when it expires the [ApiClient] 401 handler clears it and the router sends
/// the user to `/login`.
class AuthRepository {
  /// Creates the repository over [_api] and [_storage].
  AuthRepository(this._api, this._storage);

  final ApiClient _api;
  final TokenStorage _storage;

  /// Signs in and persists the session. Returns the authenticated user.
  Future<AppUser> login({required String email, required String password}) async {
    final data = await _api.post(
      ApiEndpoints.login,
      body: {'email': email.trim(), 'password': password},
    );
    return _persistFromAuthPayload(data);
  }

  /// Registers a new account. Depending on server config the account may need
  /// email verification before login; returns the user payload if one is given.
  Future<Map<String, dynamic>> register({
    required String displayName,
    required String email,
    required String password,
  }) async {
    final data = await _api.post(
      ApiEndpoints.register,
      body: {'display_name': displayName.trim(), 'email': email.trim(), 'password': password},
    );
    return data is Map<String, dynamic> ? data : <String, dynamic>{};
  }

  /// Fetches the current user (`/auth/me`), refreshing cached identity fields.
  Future<AppUser> me() async {
    final data = await _api.get(ApiEndpoints.me);
    final raw = (data is Map && data['user'] is Map) ? data['user'] : data;
    final user = AppUser.fromJson(Map<String, dynamic>.from(raw as Map));
    await _storage.save(token: (await _storage.readToken()) ?? '', userId: user.id, displayName: user.displayName);
    return user;
  }

  /// Reads the persisted JWT, or null when signed out.
  Future<String?> currentToken() => _storage.readToken();

  /// Clears the session.
  Future<void> logout() => _storage.clear();

  Future<AppUser> _persistFromAuthPayload(Object? data) async {
    final map = Map<String, dynamic>.from(data as Map);
    final token = map['token'] as String?;
    final user = AppUser.fromJson(Map<String, dynamic>.from(map['user'] as Map));
    if (token == null || token.isEmpty) {
      throw const _AuthFormatException();
    }
    await _storage.save(token: token, userId: user.id, displayName: user.displayName);
    return user;
  }
}

class _AuthFormatException implements Exception {
  const _AuthFormatException();
  @override
  String toString() => 'The server response did not contain a session token.';
}
