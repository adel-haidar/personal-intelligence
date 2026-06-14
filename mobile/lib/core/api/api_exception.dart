import 'package:dio/dio.dart';

/// A normalised, user-presentable API failure.
///
/// Every network call in the app surfaces one of these instead of leaking raw
/// [DioException]s, so UI error states can show a calm, honest message and a
/// retry button.
class ApiException implements Exception {
  /// Creates an [ApiException] with a user-facing [message].
  const ApiException(this.message, {this.statusCode, this.isAuthError = false});

  /// Calm, sentence-case message safe to show the user.
  final String message;

  /// HTTP status code if the failure came from a response.
  final int? statusCode;

  /// True for 401s after a failed token refresh — triggers a redirect to login.
  final bool isAuthError;

  /// Maps a [DioException] to a friendly [ApiException].
  factory ApiException.fromDio(DioException e) {
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return const ApiException('The server took too long to respond. Try again.');
      case DioExceptionType.connectionError:
        return const ApiException('Can\'t reach your server. Check your connection.');
      case DioExceptionType.badCertificate:
        return const ApiException('The server\'s security certificate could not be verified.');
      case DioExceptionType.cancel:
        return const ApiException('The request was cancelled.');
      case DioExceptionType.badResponse:
      case DioExceptionType.unknown:
        final status = e.response?.statusCode;
        final serverMsg = _extractMessage(e.response?.data);
        if (status == 401) {
          return ApiException(
            serverMsg ?? 'Your session has expired. Please sign in again.',
            statusCode: 401,
            isAuthError: true,
          );
        }
        if (status != null && status >= 500) {
          return ApiException(
            'Something went wrong on the server. Please try again.',
            statusCode: status,
          );
        }
        return ApiException(serverMsg ?? 'Something went wrong. Please try again.', statusCode: status);
    }
  }

  /// Pulls a human message out of the backend's `{"error": "..."}` /
  /// `{"detail": "..."}` shapes.
  static String? _extractMessage(Object? data) {
    if (data is Map) {
      final err = data['error'] ?? data['detail'] ?? data['message'];
      if (err is String && err.isNotEmpty) return err;
      if (err is List && err.isNotEmpty) {
        final first = err.first;
        if (first is Map && first['msg'] is String) return first['msg'] as String;
      }
    }
    if (data is String && data.isNotEmpty && data.length < 200) return data;
    return null;
  }

  @override
  String toString() => message;
}
