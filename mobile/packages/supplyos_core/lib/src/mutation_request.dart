import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'failure.dart';
import 'json_contract.dart';
import 'session.dart' show SessionKey;

enum MutationMethod { post, put, patch, delete }

/// A reviewed endpoint contract, not a global acceptance of any 2xx response.
final class JsonMutationEndpoint<Q, T> {
  JsonMutationEndpoint({
    required this.method,
    required this.path,
    required this.expectedStatus,
    required this.encode,
    required this.decode,
    this.supportsIdempotency = false,
  }) {
    if (!RegExp(r'^/[a-z0-9][a-z0-9/_-]*$').hasMatch(path) ||
        path.contains('//') ||
        path.split('/').any((part) => part == 'auth' || part == 'setup') ||
        !const {200, 201, 204}.contains(expectedStatus)) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
  }

  final MutationMethod method;
  final String path;
  final int expectedStatus;

  /// Opt in only when the server binds this UUID to the original actor/request.
  final bool supportsIdempotency;
  final Map<String, Object?>? Function(Q input) encode;

  /// Validate receipt binding against the frozen body, key and account scope.
  final FutureOr<T> Function(Object? response, MutationRequest<T> request)
  decode;

  MutationRequest<T> createRequest(
    Q input, {
    required SessionKey scope,
    String? idempotencyKey,
  }) {
    if (supportsIdempotency
        ? idempotencyKey == null || !isUuid(idempotencyKey)
        : idempotencyKey != null) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
    try {
      final inputBody = encode(input);
      final body = inputBody == null
          ? null
          : _freezeJson(inputBody, 0) as Map<String, Object?>;
      final encoded = body == null ? null : jsonEncode(body);
      if (encoded != null && utf8.encode(encoded).length > 64 * 1024) {
        throw const AppFailure(FailureKind.invalidRequest);
      }
      return MutationRequest._(
        scope: scope,
        method: method,
        path: path,
        expectedStatus: expectedStatus,
        body: body,
        encodedBody: encoded,
        idempotencyKey: idempotencyKey?.toLowerCase(),
        decode: decode,
      );
    } catch (_) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
  }
}

/// Memory-only original request. There is no body/key/scope replacement API.
final class MutationRequest<T> {
  const MutationRequest._({
    required this.scope,
    required this.method,
    required this.path,
    required this.expectedStatus,
    required this.body,
    required this.encodedBody,
    required this.idempotencyKey,
    required this._decode,
  });

  final SessionKey scope;
  final MutationMethod method;
  final String path;
  final int expectedStatus;
  final Map<String, Object?>? body;
  final String? encodedBody;
  final String? idempotencyKey;
  final FutureOr<T> Function(Object?, MutationRequest<T>) _decode;

  Future<MutationResponse<T>> decodeResponse(
    int status,
    Object? response,
  ) async {
    if (status != expectedStatus || (status == 204 && response != null)) {
      throw AppFailure(
        FailureKind.invalidResponse,
        statusCode: status,
        isOutcomeUncertain: true,
      );
    }
    final value = await _decode(response, this);
    return MutationResponse(statusCode: status, value: value);
  }
}

final class MutationResponse<T> {
  const MutationResponse({required this.statusCode, required this.value});

  final int statusCode;
  final T value;
}

Object? _freezeJson(Object? input, int depth) {
  if (depth > 32 || input is TypedData) {
    throw const AppFailure(FailureKind.invalidRequest);
  }
  if (input == null || input is String || input is bool || input is int) {
    return input;
  }
  if (input is double && input.isFinite) return input;
  if (input is List) {
    return List<Object?>.unmodifiable([
      for (final Object? value in input) _freezeJson(value, depth + 1),
    ]);
  }
  if (input is Map) {
    final result = <String, Object?>{};
    for (final entry in input.entries) {
      final key = entry.key;
      if (key is! String ||
          RegExp(
            r'(password|passwd|passphrase|token|secret|credential|authorization|cookie|apikey|otp|verificationcode|recoverycode)',
          ).hasMatch(key.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]'), ''))) {
        throw const AppFailure(FailureKind.invalidRequest);
      }
      result[key] = _freezeJson(entry.value, depth + 1);
    }
    return Map<String, Object?>.unmodifiable(result);
  }
  throw const AppFailure(FailureKind.invalidRequest);
}
