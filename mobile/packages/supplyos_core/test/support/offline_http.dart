import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

const userAId = '11111111-1111-4111-8111-111111111111';
const userBId = '22222222-2222-4222-8222-222222222222';
const tenantAId = '33333333-3333-4333-8333-333333333333';
const tenantBId = '44444444-4444-4444-8444-444444444444';
const orderAId = '55555555-5555-4555-8555-555555555555';
const orderBId = '66666666-6666-4666-8666-666666666666';

Map<String, Object?> userJson({
  String id = userAId,
  String tenantId = tenantAId,
  String role = 'customer',
}) => {
  'id': id,
  'tenant_id': tenantId,
  'email': 'fixture@offline.test',
  'full_name': id == userAId ? 'Fixture A' : 'Fixture B',
  'role': role,
};

List<String> sessionCookies(String marker, {bool secure = true}) => [
  'access_token=fixture-access-$marker; Path=/; HttpOnly${secure ? '; Secure' : ''}',
  'refresh_token=fixture-refresh-$marker; Path=/; HttpOnly${secure ? '; Secure' : ''}',
];

class OfflineRequest {
  const OfflineRequest(this.options, this.body);

  final RequestOptions options;
  final Object? body;

  String get path => options.path;
  String get method => options.method;
  String get cookie => options.headers['cookie']?.toString() ?? '';
}

class OfflineResponse {
  const OfflineResponse(
    this.data, {
    this.status = 200,
    this.cookies = const [],
    this.isRedirect = false,
  });

  final Object? data;
  final int status;
  final List<String> cookies;
  final bool isRedirect;

  ResponseBody toBody() => ResponseBody.fromString(
    status == 204 ? '' : jsonEncode(data),
    status,
    isRedirect: isRedirect,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
      if (cookies.isNotEmpty) 'set-cookie': cookies,
    },
  );
}

class OfflineBackend {
  OfflineBackend(this.handle);

  FutureOr<OfflineResponse> Function(OfflineRequest request) handle;
  final requests = <OfflineRequest>[];
  final _waiting = <(String, int, Completer<OfflineRequest>)>[];
  final adapters = <OfflineAdapter>[];

  int count(String path) =>
      requests.where((request) => request.path == path).length;

  Future<OfflineRequest> requested(String path, {int occurrence = 1}) {
    final existing = requests.where((request) => request.path == path).toList();
    if (existing.length >= occurrence) {
      return Future.value(existing[occurrence - 1]);
    }
    final completer = Completer<OfflineRequest>();
    _waiting.add((path, occurrence, completer));
    return completer.future;
  }

  HttpClientAdapter adapter() {
    final adapter = OfflineAdapter(this);
    adapters.add(adapter);
    return adapter;
  }

  DioSessionTransport transport(ApiConfig config) =>
      DioSessionTransport(config, adapterFactory: adapter);

  void _record(OfflineRequest request) {
    requests.add(request);
    for (final waiting in _waiting.toList()) {
      if (waiting.$1 == request.path && count(request.path) >= waiting.$2) {
        _waiting.remove(waiting);
        waiting.$3.complete(request);
      }
    }
  }
}

class OfflineAdapter implements HttpClientAdapter {
  OfflineAdapter(this.backend);

  final OfflineBackend backend;
  bool isClosed = false;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (isClosed) throw StateError('Offline adapter is closed');
    final bytes = <int>[];
    if (requestStream != null) {
      await for (final chunk in requestStream) {
        bytes.addAll(chunk);
      }
    }
    final body = bytes.isEmpty ? null : jsonDecode(utf8.decode(bytes));
    final request = OfflineRequest(options, body);
    backend._record(request);
    // Deliberately allow delayed fixture replies after cancellation/close.
    // The session, not the fixture adapter, must reject stale work.
    return (await backend.handle(request)).toBody();
  }

  @override
  void close({bool force = false}) => isClosed = true;
}

ApiConfig fixtureConfig() => ApiConfig.parse('https://api.supplyos.app/api/v1');

SessionController fixtureSession(
  OfflineBackend backend, {
  String role = 'customer',
}) => SessionController(
  config: fixtureConfig(),
  expectedRole: role,
  transportFactory: backend.transport,
);

Future<AsyncValue<T>> settledQuery<T>(
  ProviderContainer container,
  ProviderListenable<AsyncValue<T>> provider,
) async {
  final completer = Completer<AsyncValue<T>>();
  final subscription = container.listen(provider, (_, next) {
    if (!next.isLoading && !completer.isCompleted) completer.complete(next);
  }, fireImmediately: true);
  try {
    return await completer.future;
  } finally {
    subscription.close();
  }
}

Future<SessionState> settledSession(
  ProviderContainer container,
  ProviderListenable<SessionState> provider,
) async {
  final completer = Completer<SessionState>();
  final subscription = container.listen(provider, (_, next) {
    if (!next.isBusy && !completer.isCompleted) completer.complete(next);
  }, fireImmediately: true);
  try {
    return await completer.future;
  } finally {
    subscription.close();
  }
}
