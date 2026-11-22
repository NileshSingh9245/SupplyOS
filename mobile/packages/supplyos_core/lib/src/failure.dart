import 'package:dio/dio.dart';

enum FailureKind {
  configuration,
  signedOut,
  wrongRole,
  invalidResponse,
  invalidCredentials,
  forbidden,
  notFound,
  rateLimited,
  timeout,
  network,
  server,
  superseded,
}

/// Only fixed, non-sensitive messages cross the transport/UI boundary.
class AppFailure implements Exception {
  const AppFailure(this.kind, {this.statusCode});

  final FailureKind kind;
  final int? statusCode;

  String get message => switch (kind) {
    FailureKind.configuration =>
      'This build has no valid API configuration. Connection is disabled.',
    FailureKind.signedOut => 'Your session ended. Sign in again.',
    FailureKind.wrongRole => 'This account cannot use this application.',
    FailureKind.invalidResponse =>
      'The server returned an unsupported response. Try again later.',
    FailureKind.invalidCredentials => 'Sign-in failed. Check your credentials.',
    FailureKind.forbidden => 'You do not have access to this resource.',
    FailureKind.notFound => 'This resource is unavailable.',
    FailureKind.rateLimited => 'Too many requests. Try again later.',
    FailureKind.timeout => 'The request timed out. Try again.',
    FailureKind.network =>
      'Unable to connect. Check your connection and retry.',
    FailureKind.server => 'The service is unavailable. Try again later.',
    FailureKind.superseded => 'This request belongs to a session that ended.',
  };

  factory AppFailure.fromDio(DioException error) {
    if (error.type == DioExceptionType.cancel) {
      return const AppFailure(FailureKind.superseded);
    }
    if (error.type == DioExceptionType.connectionTimeout ||
        error.type == DioExceptionType.sendTimeout ||
        error.type == DioExceptionType.receiveTimeout) {
      return const AppFailure(FailureKind.timeout);
    }
    final status = error.response?.statusCode;
    final kind = switch (status) {
      401 => FailureKind.signedOut,
      403 => FailureKind.forbidden,
      404 => FailureKind.notFound,
      429 => FailureKind.rateLimited,
      final int value when value >= 500 => FailureKind.server,
      final int _ => FailureKind.invalidResponse,
      _ => FailureKind.network,
    };
    return AppFailure(kind, statusCode: status);
  }

  static AppFailure safe(Object error) => error is AppFailure
      ? error
      : const AppFailure(FailureKind.invalidResponse);

  @override
  String toString() => message;
}
