import 'dart:async';

import 'package:dio/dio.dart';

import 'api_config.dart';
import 'failure.dart';
import 'http_cookies.dart';
import 'http_platform_stub.dart'
    if (dart.library.io) 'http_platform_io.dart'
    if (dart.library.js_interop) 'http_platform_web.dart'
    as platform;

typedef SessionTransportFactory = DioSessionTransport Function(
  ApiConfig config,
);

class DioSessionTransport {
  DioSessionTransport(this.config, {this.adapterFactory}) {
    _dio = _newDio();
    _cookies = platform.configureSession(_dio, config);
    if (adapterFactory != null) _dio.httpClientAdapter = adapterFactory!();
  }

  final ApiConfig config;
  final HttpClientAdapter Function()? adapterFactory;
  late final Dio _dio;
  late final SessionCookies _cookies;
  final _pending = <CancelToken>{};
  bool _acceptsRequests = true;
  Dio? _logoutDio;
  CancelToken? _logoutToken;

  Dio _newDio() => Dio(
    BaseOptions(
      baseUrl: config.baseUrl,
      connectTimeout: const Duration(seconds: 15),
      sendTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 30),
      contentType: Headers.jsonContentType,
      responseType: ResponseType.json,
      followRedirects: false,
      maxRedirects: 0,
      headers: const {
        'Accept': 'application/json',
        'Cache-Control': 'no-store',
      },
    ),
  );

  Future<Object?> send(
    String method,
    String path, {
    Object? data,
    Map<String, Object?>? queryParameters,
    CancelToken? cancelToken,
  }) async {
    if (!_acceptsRequests) throw const AppFailure(FailureKind.superseded);
    if (!RegExp(r'^/[a-z0-9][a-z0-9/_-]*$').hasMatch(path) ||
        path.contains('//')) {
      throw const AppFailure(FailureKind.invalidResponse);
    }
    final token = cancelToken ?? CancelToken();
    _pending.add(token);
    try {
      final response = await _dio.request<Object?>(
        path,
        data: data,
        queryParameters: queryParameters,
        cancelToken: token,
        options: Options(method: method),
      );
      if (!_acceptsRequests || token.isCancelled) {
        throw const AppFailure(FailureKind.superseded);
      }
      if (response.isRedirect || response.statusCode != 200) {
        throw const AppFailure(FailureKind.invalidResponse);
      }
      return response.data;
    } on DioException catch (error) {
      throw AppFailure.fromDio(error);
    } finally {
      _pending.remove(token);
    }
  }

  void _cancelPending() {
    _acceptsRequests = false;
    for (final token in _pending.toList()) {
      token.cancel('Session ended');
    }
    _pending.clear();
  }

  Future<bool> logout() async {
    if (!_acceptsRequests) return false;
    final dio = _newDio();
    final logoutCookies = _cookies.forkForLogout(dio);
    if (adapterFactory != null) dio.httpClientAdapter = adapterFactory!();
    _logoutDio = dio;
    final token = _logoutToken = CancelToken();
    _cancelPending();
    await _cookies.clear();
    _dio.close(force: true);
    try {
      final response = await dio.post<Object?>(
        '/auth/logout',
        cancelToken: token,
      );
      return !response.isRedirect &&
          (response.statusCode == 200 || response.statusCode == 204);
    } on DioException {
      return false;
    } finally {
      await logoutCookies.clear();
      dio.close(force: true);
      _logoutDio = null;
      _logoutToken = null;
    }
  }

  void dispose() {
    _cancelPending();
    unawaited(_cookies.clear());
    _dio.close(force: true);
    _logoutToken?.cancel('Application closed');
    _logoutDio?.close(force: true);
  }
}
