import 'dart:async';

import 'package:dio/dio.dart';

import '../auth/token_storage.dart';
import 'api_endpoints.dart';
import 'api_exception.dart';

/// Thin typed wrapper over Dio.
///
/// * Injects `Authorization: Bearer <jwt>` on every request.
/// * On a 401 it clears the session and notifies via [onUnauthorized] so the
///   router can redirect to `/login`. The backend has no refresh endpoint, so
///   there is no silent token refresh — an expired 7-day JWT means re-login.
/// * Converts every [DioException] into a calm [ApiException].
class ApiClient {
  /// Builds a client. [onUnauthorized] is called once per unrecoverable 401.
  ApiClient({required TokenStorage tokenStorage, FutureOr<void> Function()? onUnauthorized})
      : _tokenStorage = tokenStorage,
        _onUnauthorized = onUnauthorized {
    _dio = Dio(
      BaseOptions(
        baseUrl: ApiEndpoints.baseUrl,
        connectTimeout: const Duration(seconds: 10),
        receiveTimeout: const Duration(seconds: 30),
        headers: {'Content-Type': 'application/json'},
      ),
    );
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await _tokenStorage.readToken();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: (error, handler) async {
          if (error.response?.statusCode == 401) {
            await _tokenStorage.clear();
            await _onUnauthorized?.call();
          }
          handler.next(error);
        },
      ),
    );
  }

  late final Dio _dio;
  final TokenStorage _tokenStorage;
  final FutureOr<void> Function()? _onUnauthorized;

  /// The underlying Dio, exposed for multipart uploads that need raw access.
  Dio get raw => _dio;

  /// GET returning the decoded JSON body.
  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _run(() => _dio.get(path, queryParameters: query));

  /// POST returning the decoded JSON body.
  Future<dynamic> post(String path, {Object? body, Map<String, dynamic>? query}) =>
      _run(() => _dio.post(path, data: body, queryParameters: query));

  /// PATCH returning the decoded JSON body.
  Future<dynamic> patch(String path, {Object? body}) => _run(() => _dio.patch(path, data: body));

  /// DELETE returning the decoded JSON body.
  Future<dynamic> delete(String path, {Object? body}) => _run(() => _dio.delete(path, data: body));

  /// Multipart upload of one or more files plus optional [fields].
  Future<dynamic> uploadFiles(
    String path, {
    required List<MultipartFile> files,
    String fileField = 'files',
    Map<String, dynamic>? fields,
  }) {
    final form = FormData();
    for (final f in files) {
      form.files.add(MapEntry(fileField, f));
    }
    fields?.forEach((k, v) => form.fields.add(MapEntry(k, '$v')));
    return _run(() => _dio.post(path, data: form));
  }

  Future<dynamic> _run(Future<Response<dynamic>> Function() request) async {
    try {
      final res = await request();
      return res.data;
    } on DioException catch (e) {
      throw ApiException.fromDio(e);
    }
  }
}
