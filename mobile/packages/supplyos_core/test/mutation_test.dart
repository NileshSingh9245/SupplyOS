import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_http.dart';

const mutationKey = '77777777-7777-4777-8777-777777777777';
const mutationScope = SessionKey(userAId, tenantAId, 'customer', 1);

Map<String, Object?> mutationBody() => {
  'resource_id': orderAId,
  'value': '1.2300',
};
Map<String, Object?> mutationReceipt() => {'id': orderAId, 'value': '1.2300'};

JsonMutationEndpoint<Map<String, Object?>, ServerDecimal> mutationEndpoint({
  int status = 201,
  bool idempotent = true,
  String path = '/payments',
  MutationMethod method = MutationMethod.post,
  FutureOr<ServerDecimal> Function(Object?, MutationRequest<ServerDecimal>)?
  decode,
}) => JsonMutationEndpoint(
  method: method,
  path: path,
  expectedStatus: status,
  supportsIdempotency: idempotent,
  encode: (input) => input,
  decode:
      decode ??
      (response, request) {
        final json = JsonObject(response);
        final value = json.decimal('value');
        final body = request.body;
        if (json.uuid('id') != body!['resource_id'] ||
            value.text != body['value']) {
          throw invalidResponse;
        }
        return value;
      },
);

OfflineBackend mutationBackend(
  FutureOr<OfflineResponse> Function(OfflineRequest) handle,
) => OfflineBackend(
  (request) => request.path == '/auth/login'
      ? OfflineResponse({
          'user': userJson(),
        }, cookies: sessionCookies('mutation'))
      : request.path == '/auth/logout'
      ? const OfflineResponse({})
      : handle(request),
);

Future<AppFailure> mutationFailure(Future<Object?> future) async {
  try {
    await future;
    fail('Expected a rejected mutation');
  } catch (error) {
    if (error is! AppFailure) rethrow;
    return error;
  }
}

void main() {
  test(
    'server-bound request key is frozen and survives uncertain retry',
    () async {
      var unavailable = true;
      final backend = mutationBackend(
        (request) => unavailable
            ? const OfflineResponse({}, status: 503)
            : OfflineResponse(mutationReceipt(), status: 201),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final mutation = SessionMutation(
        session: session,
        endpoint: mutationEndpoint(),
      );
      addTearDown(mutation.dispose);
      await mutationFailure(
        mutation.submit(mutationBody(), idempotencyKey: mutationKey),
      );
      final original = mutation.snapshot.request!;
      expect(original.idempotencyKey, mutationKey);
      expect(
        () => mutation.submit(mutationBody(), idempotencyKey: orderAId),
        throwsA(isA<AppFailure>()),
      );
      unavailable = false;
      expect((await mutation.retry()).value.text, '1.2300');
      expect(identical(mutation.snapshot.request, original), isTrue);
      expect(
        backend.requests.last.options.headers['X-Idempotency-Key'],
        mutationKey,
      );
      expect(backend.requests.last.encodedBody, original.encodedBody);
    },
  );

  for (final idempotent in [true, false]) {
    test(
      'invalid supplied key is rejected before dispatch ($idempotent)',
      () async {
        final backend = mutationBackend(
          (request) => OfflineResponse(mutationReceipt(), status: 201),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final mutation = SessionMutation(
          session: session,
          endpoint: mutationEndpoint(idempotent: idempotent),
        );
        addTearDown(mutation.dispose);
        expect(
          () => mutation.submit(
            mutationBody(),
            idempotencyKey: idempotent ? 'not-a-uuid' : mutationKey,
          ),
          throwsA(isA<AppFailure>()),
        );
        expect(backend.count('/payments'), 0);
        expect(mutation.snapshot.phase, MutationPhase.ready);
      },
    );
  }

  for (final field in ['tenant_id', 'actor_id']) {
    test(
      'typed receipt validator uses frozen scope to reject a wrong $field',
      () async {
        var wrongScope = true;
        final backend = mutationBackend(
          (request) => OfflineResponse({
            ...mutationReceipt(),
            'tenant_id': wrongScope && field == 'tenant_id'
                ? tenantBId
                : tenantAId,
            'actor_id': wrongScope && field == 'actor_id' ? userBId : userAId,
          }, status: 201),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final endpoint = mutationEndpoint(
          decode: (response, original) {
            final json = JsonObject(response);
            if (json.uuid('tenant_id') != original.scope.tenantId ||
                json.uuid('actor_id') != original.scope.userId ||
                json.uuid('id') != original.body!['resource_id']) {
              throw invalidResponse;
            }
            return json.decimal('value');
          },
        );
        final mutation = SessionMutation(session: session, endpoint: endpoint);
        addTearDown(mutation.dispose);
        final failure = await mutationFailure(mutation.submit(mutationBody()));
        expect(failure.isOutcomeUncertain, isTrue);
        expect(mutation.snapshot.phase, MutationPhase.uncertain);
        expect(mutation.snapshot.response, isNull);
        final original = mutation.snapshot.request!;
        wrongScope = false;
        expect((await mutation.retry()).value.text, '1.2300');
        expect(identical(mutation.snapshot.request, original), isTrue);
        expect(backend.requests.last.encodedBody, original.encodedBody);
        expect(
          backend.requests.last.options.headers['X-Idempotency-Key'],
          original.idempotencyKey,
        );
      },
    );
  }

  for (final status in [200, 201]) {
    test(
      'JSON mutation validates exactly $status, body and UUID header',
      () async {
        final backend = mutationBackend(
          (request) => OfflineResponse(mutationReceipt(), status: status),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final request = mutationEndpoint(status: status).createRequest(
          mutationBody(),
          scope: session.snapshot.key!,
          idempotencyKey: mutationKey,
        );
        final response = await session.mutate(request);
        expect(response.statusCode, status);
        expect(response.value.text, '1.2300');
        final sent = backend.requests.last;
        expect(sent.method, 'POST');
        expect(sent.body, mutationBody());
        expect(sent.encodedBody, request.encodedBody);
        expect(sent.options.headers['X-Idempotency-Key'], mutationKey);
        expect(sent.options.contentType, Headers.jsonContentType);
        expect(sent.options.headers['Accept'], Headers.jsonContentType);
        expect(sent.cookie.contains('fixture-access-mutation'), isTrue);
        final names = sent.options.headers.keys
            .map((key) => key.toLowerCase())
            .toSet();
        expect(
          names.intersection({
            'authorization',
            'origin',
            'referer',
            'x-setup-authorization',
          }),
          isEmpty,
        );
        expect(names.any((key) => key.startsWith('sec-fetch-')), isFalse);
        expect(sent.options.followRedirects, isFalse);
        expect(sent.options.connectTimeout, const Duration(seconds: 15));
        expect(sent.options.sendTimeout, const Duration(seconds: 15));
        expect(sent.options.receiveTimeout, const Duration(seconds: 30));
        expect(backend.count('/auth/refresh'), 0);
      },
    );
  }

  test(
    '204 deletion accepts no content and does not invent a JSON receipt',
    () async {
      final backend = mutationBackend(
        (request) => const OfflineResponse(null, status: 204),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      var decoded = 0;
      final endpoint = JsonMutationEndpoint<String, void>(
        method: MutationMethod.delete,
        path: '/customers/$userAId/prices/$orderAId',
        expectedStatus: 204,
        encode: (_) => null,
        decode: (response, request) {
          decoded++;
          expect(response, isNull);
          expect(request.body, isNull);
        },
      );
      final response = await session.mutate(
        endpoint.createRequest('unused', scope: session.snapshot.key!),
      );
      expect(response.statusCode, 204);
      expect(decoded, 1);
      expect(backend.requests.last.body, isNull);
      expect(backend.requests.last.method, 'DELETE');
      expect(
        backend.requests.last.options.headers.containsKey('X-Idempotency-Key'),
        isFalse,
      );
    },
  );

  for (final method in MutationMethod.values) {
    test('explicit ${method.name} mutation method is preserved', () async {
      final backend = mutationBackend(
        (request) => OfflineResponse(mutationReceipt(), status: 200),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      await session.mutate(
        mutationEndpoint(
          status: 200,
          method: method,
          idempotent: false,
        ).createRequest(mutationBody(), scope: session.snapshot.key!),
      );
      expect(backend.requests.last.method, method.name.toUpperCase());
      expect(
        backend.requests.last.options.headers.containsKey('X-Idempotency-Key'),
        isFalse,
      );
    });
  }

  for (final status in [200, 202, 204, 299, 302]) {
    test(
      'unexpected mutation status $status is uncertain, never a broad 2xx success',
      () async {
        final backend = mutationBackend(
          (request) => OfflineResponse(mutationReceipt(), status: status),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final mutation = SessionMutation(
          session: session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        final failure = await mutationFailure(mutation.submit(mutationBody()));
        expect(failure.isOutcomeUncertain, isTrue);
        expect(failure.statusCode, status);
        expect(mutation.snapshot.phase, MutationPhase.uncertain);
        expect(mutation.snapshot.response, isNull);
        expect(backend.count('/payments'), 1);
      },
    );
  }

  for (final status in [201, 202, 204, 299]) {
    test(
      'existing GET still rejects $status after mutation support is added',
      () async {
        final backend = mutationBackend(
          (request) => OfflineResponse({}, status: status),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        await expectLater(
          session.get('/orders', scope: session.snapshot.key!),
          throwsA(isA<AppFailure>()),
        );
        expect(backend.count('/orders'), 1);
      },
    );
  }

  for (final response in [
    const OfflineResponse(null, status: 201, rawBody: '{private-invalid-json'),
    const OfflineResponse(
      {},
      status: 201,
      headers: {
        'content-type': ['text/html'],
      },
    ),
    const OfflineResponse({}, status: 201, isRedirect: true),
    const OfflineResponse({'id': orderBId, 'value': '1.2300'}, status: 201),
    const OfflineResponse({'id': orderAId, 'value': '1.23'}, status: 201),
  ].indexed) {
    test(
      'malformed or unbound success ${response.$1 + 1} retains the uncertain original',
      () async {
        final backend = mutationBackend((request) => response.$2);
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final mutation = SessionMutation(
          session: session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        final failure = await mutationFailure(mutation.submit(mutationBody()));
        expect(failure.isOutcomeUncertain, isTrue);
        expect(failure.message.contains('private-invalid'), isFalse);
        expect(mutation.snapshot.phase, MutationPhase.uncertain);
        expect(mutation.snapshot.response, isNull);
        expect(
          () => mutation.submit(mutationBody()),
          throwsA(isA<AppFailure>()),
        );
      },
    );
  }

  test('existing GET still rejects malformed HTTP 200 JSON', () async {
    final backend = mutationBackend(
      (request) =>
          const OfflineResponse(null, rawBody: '{private-invalid-json'),
    );
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', 'fixture-only');
    final failure = await mutationFailure(
      session.get('/orders', scope: session.snapshot.key!),
    );
    expect(failure.message.contains('private-invalid'), isFalse);
    expect(failure.isOutcomeUncertain, isFalse);
    expect(backend.count('/orders'), 1);
  });

  test(
    'duplicate Retry-After metadata cannot turn a known 429 into uncertainty',
    () async {
      final backend = mutationBackend(
        (request) => const OfflineResponse(
          {'detail': 'private-rate-limit'},
          status: 429,
          headers: {
            'retry-after': ['15', '30'],
          },
        ),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final request = mutationEndpoint().createRequest(
        mutationBody(),
        scope: session.snapshot.key!,
        idempotencyKey: mutationKey,
      );
      final failure = await mutationFailure(session.mutate(request));
      expect(failure.kind, FailureKind.rateLimited);
      expect(failure.statusCode, 429);
      expect(failure.isOutcomeUncertain, isFalse);
      expect(failure.retryAfterSeconds, isNull);
      expect(failure.message.contains('private-rate-limit'), isFalse);
    },
  );

  test(
    'a nonempty 204 response is uncertain despite the expected status',
    () async {
      final backend = mutationBackend(
        (request) => const OfflineResponse(null, status: 204, rawBody: '{}'),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final endpoint = JsonMutationEndpoint<int, void>(
        method: MutationMethod.delete,
        path: '/products/$orderAId',
        expectedStatus: 204,
        encode: (_) => null,
        decode: (_, _) => fail('Must not decode nonempty 204'),
      );
      final failure = await mutationFailure(
        session.mutate(endpoint.createRequest(0, scope: session.snapshot.key!)),
      );
      expect(failure.isOutcomeUncertain, isTrue);
    },
  );

  for (final entry in [
    (409, FailureKind.conflict),
    (422, FailureKind.validation),
    (429, FailureKind.rateLimited),
  ]) {
    test(
      '${entry.$1} is typed and sanitizes private validation/conflict data',
      () async {
        final backend = mutationBackend(
          (request) => OfflineResponse(
            {
              'detail': [
                {
                  'loc': ['body', 'value'],
                  'msg': 'private-upstream',
                  'input': 'private-echo',
                  'ctx': {'error': 'private-context'},
                },
              ],
            },
            status: entry.$1,
            headers: {
              'retry-after': ['15'],
            },
          ),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final mutation = SessionMutation(
          session: session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        final failure = await mutationFailure(mutation.submit(mutationBody()));
        expect(failure.kind, entry.$2);
        expect(failure.statusCode, entry.$1);
        expect(failure.isOutcomeUncertain, isFalse);
        expect(failure.retryAfterSeconds, entry.$1 == 429 ? 15 : null);
        expect(failure.toString().contains('private-'), isFalse);
        expect(mutation.snapshot.phase, MutationPhase.rejected);
        expect(mutation.snapshot.response, isNull);
        expect(backend.count('/payments'), 1);
        expect(backend.count('/auth/refresh'), 0);
      },
    );
  }

  test(
    '429 Retry-After metadata is bounded and never echoes arbitrary headers',
    () async {
      var retry = '999999999999999999999999999';
      final backend = mutationBackend(
        (request) => OfflineResponse(
          {},
          status: 429,
          headers: {
            'retry-after': [retry],
          },
        ),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final mutation = SessionMutation(
        session: session,
        endpoint: mutationEndpoint(),
      );
      addTearDown(mutation.dispose);
      for (final value in [retry, '0', '-1', 'private-retry', '3601']) {
        retry = value;
        final failure = await mutationFailure(mutation.submit(mutationBody()));
        expect(failure.retryAfterSeconds, isNull);
        expect(failure.message.contains('private'), isFalse);
      }
    },
  );

  for (final status in [408, 500, 503]) {
    test(
      '$status freezes the uncertain body/key and never automatically retries POST',
      () async {
        final backend = mutationBackend(
          (request) =>
              OfflineResponse({'detail': 'private-upstream'}, status: status),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final mutation = SessionMutation(
          session: session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        final failure = await mutationFailure(mutation.submit(mutationBody()));
        await pumpEventQueue();
        expect(failure.isOutcomeUncertain, isTrue);
        expect(mutation.snapshot.phase, MutationPhase.uncertain);
        expect(mutation.snapshot.request!.scope, session.snapshot.key);
        expect(isUuid(mutation.snapshot.request!.idempotencyKey!), isTrue);
        expect(mutation.snapshot.request!.idempotencyKey![14], '4');
        expect(backend.count('/payments'), 1);
        expect(backend.count('/auth/refresh'), 0);
      },
    );
  }

  for (final type in [
    DioExceptionType.connectionError,
    DioExceptionType.receiveTimeout,
  ]) {
    test(
      '${type.name} is an uncertain mutation without private network-error echo',
      () async {
        final backend = mutationBackend(
          (request) => throw DioException(
            requestOptions: request.options,
            type: type,
            message: 'private-network-input',
          ),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final mutation = SessionMutation(
          session: session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        final failure = await mutationFailure(mutation.submit(mutationBody()));
        expect(failure.isOutcomeUncertain, isTrue);
        expect(failure.toString().contains('private-network'), isFalse);
        expect(mutation.snapshot.phase, MutationPhase.uncertain);
        expect(backend.count('/payments'), 1);
      },
    );
  }

  test('uncertain mutable input is deeply frozen and explicit retry sends identical original bytes/key', () async {
    var succeeds = false;
    var encodes = 0;
    final backend = mutationBackend(
      (request) => succeeds
          ? OfflineResponse(mutationReceipt(), status: 201)
          : const OfflineResponse({}, status: 503),
    );
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', 'fixture-only');
    final base = mutationEndpoint();
    final endpoint = JsonMutationEndpoint<Map<String, Object?>, ServerDecimal>(
      method: base.method,
      path: base.path,
      expectedStatus: base.expectedStatus,
      supportsIdempotency: true,
      encode: (input) {
        encodes++;
        return input;
      },
      decode: base.decode,
    );
    final mutation = SessionMutation(session: session, endpoint: endpoint);
    addTearDown(mutation.dispose);
    final rows = <Object?>[
      {'quantity': '1.000'},
    ];
    final input = {...mutationBody(), 'items': rows};
    await mutationFailure(mutation.submit(input));
    final original = mutation.snapshot.request!;
    final first = backend.requests.last;
    input['value'] = '9.99';
    (rows.single! as Map<String, String>)['quantity'] = '2.000';
    rows.add({'quantity': '3.000'});
    expect(
      () => mutation.submit(input),
      throwsA(
        isA<AppFailure>().having(
          (f) => f.kind,
          'kind',
          FailureKind.intentPending,
        ),
      ),
    );
    expect(encodes, 1);
    expect(original.body!['value'], '1.2300');
    final frozenRows = original.body!['items']! as List<Object?>;
    expect(frozenRows, [
      {'quantity': '1.000'},
    ]);
    expect(() => original.body!['value'] = '2.00', throwsUnsupportedError);
    expect(() => frozenRows.add(null), throwsUnsupportedError);
    expect(
      () => (frozenRows.single! as Map<String, Object?>)['quantity'] = '2.000',
      throwsUnsupportedError,
    );
    succeeds = true;
    final response = await mutation.retry();
    expect(response.value.text, '1.2300');
    expect(identical(mutation.snapshot.request, original), isTrue);
    expect(encodes, 1);
    expect(backend.requests.last.encodedBody, first.encodedBody);
    expect(
      backend.requests.last.options.headers['X-Idempotency-Key'],
      first.options.headers['X-Idempotency-Key'],
    );
    expect(backend.count('/payments'), 2);
    await mutation.submit(mutationBody());
    expect(encodes, 2);
    expect(
      mutation.snapshot.request!.idempotencyKey,
      isNot(original.idempotencyKey),
    );
  });

  for (final status in [409, 422, 429]) {
    test(
      'a later retry $status cannot discard an earlier uncertain intent',
      () async {
        var reply = 503;
        final backend = mutationBackend(
          (request) => OfflineResponse({}, status: reply),
        );
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', 'fixture-only');
        final mutation = SessionMutation(
          session: session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        await mutationFailure(mutation.submit(mutationBody()));
        final original = mutation.snapshot.request!;
        reply = status;
        expect(
          (await mutationFailure(mutation.retry())).isOutcomeUncertain,
          isTrue,
        );
        expect(mutation.snapshot.phase, MutationPhase.uncertain);
        expect(identical(mutation.snapshot.request, original), isTrue);
        expect(
          () => mutation.submit(mutationBody()),
          throwsA(isA<AppFailure>()),
        );
        expect(backend.requests.last.encodedBody, original.encodedBody);
        expect(
          backend.requests.last.options.headers['X-Idempotency-Key'],
          original.idempotencyKey,
        );
      },
    );
  }

  test(
    'non-idempotent uncertainty is frozen but cannot be explicitly replayed',
    () async {
      final backend = mutationBackend(
        (request) => const OfflineResponse({}, status: 503),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final mutation = SessionMutation(
        session: session,
        endpoint: mutationEndpoint(idempotent: false),
      );
      addTearDown(mutation.dispose);
      await mutationFailure(mutation.submit(mutationBody()));
      expect(mutation.snapshot.request!.idempotencyKey, isNull);
      expect(mutation.snapshot.canRetry, isFalse);
      expect(
        () => mutation.retry(),
        throwsA(
          isA<AppFailure>().having(
            (f) => f.kind,
            'kind',
            FailureKind.retryUnsafe,
          ),
        ),
      );
      expect(() => mutation.submit(mutationBody()), throwsA(isA<AppFailure>()));
      expect(backend.count('/payments'), 1);
    },
  );

  test('reconciliation validates the original receipt/status before releasing uncertainty', () async {
    final backend = mutationBackend(
      (request) => const OfflineResponse({}, status: 503),
    );
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', 'fixture-only');
    final mutation = SessionMutation(
      session: session,
      endpoint: mutationEndpoint(),
    );
    addTearDown(mutation.dispose);
    await mutationFailure(mutation.submit(mutationBody()));
    final original = mutation.snapshot.request!;
    expect(
      await mutation.reconcile((request, token) async {
        expect(identical(request, original), isTrue);
        expect(token.isCancelled, isFalse);
        return const MutationReconciliation.unresolved();
      }),
      isNull,
    );
    expect(mutation.snapshot.phase, MutationPhase.uncertain);
    for (final outcome in [
      MutationReconciliation.applied(statusCode: 200, body: mutationReceipt()),
      const MutationReconciliation.applied(
        statusCode: 201,
        body: {'id': orderBId, 'value': '1.2300'},
      ),
    ]) {
      final failure = await mutationFailure(
        mutation.reconcile((_, _) async => outcome),
      );
      expect(failure.isOutcomeUncertain, isTrue);
      expect(mutation.snapshot.phase, MutationPhase.uncertain);
      expect(identical(mutation.snapshot.request, original), isTrue);
      expect(() => mutation.submit(mutationBody()), throwsA(isA<AppFailure>()));
    }
    final response = await mutation.reconcile(
      (_, _) async => MutationReconciliation.applied(
        statusCode: 201,
        body: mutationReceipt(),
      ),
    );
    expect(response!.value.text, '1.2300');
    expect(mutation.snapshot.phase, MutationPhase.succeeded);
    expect(backend.count('/payments'), 1);
  });

  test('authoritative not-applied reconciliation alone unlocks a new intent without replay', () async {
    final backend = mutationBackend(
      (request) => const OfflineResponse({}, status: 503),
    );
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', 'fixture-only');
    final mutation = SessionMutation(
      session: session,
      endpoint: mutationEndpoint(idempotent: false),
    );
    addTearDown(mutation.dispose);
    await mutationFailure(mutation.submit(mutationBody()));
    await mutation.reconcile(
      (_, _) async => const MutationReconciliation.notApplied(),
    );
    expect(mutation.snapshot.phase, MutationPhase.rejected);
    await mutationFailure(
      mutation.submit({...mutationBody(), 'value': '2.0000'}),
    );
    expect(mutation.snapshot.request!.body!['value'], '2.0000');
    expect(backend.count('/payments'), 2);
  });

  test(
    'sending and reconciliation both block body edits and concurrent attempts',
    () async {
      final reply = Completer<OfflineResponse>();
      final lookup = Completer<MutationReconciliation>();
      final backend = mutationBackend((request) => reply.future);
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final mutation = SessionMutation(
        session: session,
        endpoint: mutationEndpoint(),
      );
      addTearDown(mutation.dispose);
      final attempt = mutationFailure(mutation.submit(mutationBody()));
      await backend.requested('/payments');
      expect(mutation.snapshot.isBusy, isTrue);
      expect(() => mutation.submit(mutationBody()), throwsA(isA<AppFailure>()));
      expect(() => mutation.retry(), throwsA(isA<AppFailure>()));
      reply.complete(const OfflineResponse({}, status: 503));
      await attempt;
      final reconciliation = mutation.reconcile((_, _) => lookup.future);
      await pumpEventQueue();
      expect(mutation.snapshot.isBusy, isTrue);
      expect(() => mutation.submit(mutationBody()), throwsA(isA<AppFailure>()));
      expect(() => mutation.retry(), throwsA(isA<AppFailure>()));
      lookup.complete(const MutationReconciliation.unresolved());
      await reconciliation;
      expect(mutation.snapshot.phase, MutationPhase.uncertain);
      expect(backend.count('/payments'), 1);
    },
  );

  for (final path in [
    '/auth/login',
    '/auth/refresh',
    '/auth/logout',
    '/auth/change-password',
    '/auth/forgot-password',
    '/auth/reset-password',
    '/auth/register-customer',
    '/setup/initialize',
    '/api/v1/auth/change-password',
    '//external.test/payments',
    '/payments?secret=fixture',
    '/payments/../auth/login',
  ].indexed) {
    test(
      'generic mutation excludes credential/unsafe endpoint ${path.$1 + 1}',
      () {
        expect(
          () => mutationEndpoint(path: path.$2),
          throwsA(isA<AppFailure>()),
        );
      },
    );
  }

  test('credential-bearing nested JSON is rejected without retaining or printing input', () {
    for (final name in [
      'password',
      'new_password',
      'current-password',
      'resetToken',
      'api_key',
      'secret',
      'credentials',
      'Authorization',
      'otp',
      'verification_code',
    ]) {
      final endpoint = mutationEndpoint();
      try {
        endpoint.createRequest(
          {
            'rows': [
              {
                'nested': {name: 'private-input'},
              },
            ],
          },
          scope: mutationScope,
          idempotencyKey: mutationKey,
        );
        fail('Credential input was accepted');
      } on AppFailure catch (failure) {
        expect(failure.kind, FailureKind.invalidRequest);
        expect(failure.message.contains('private-input'), isFalse);
        expect(failure.message.contains(name), isFalse);
      }
    }
  });

  test('only JSON types and bounded immutable bodies enter a request', () {
    final cycle = <String, Object?>{};
    cycle['self'] = cycle;
    for (final input in <Map<String, Object?>>[
      {'value': double.nan},
      {'value': double.infinity},
      {'value': Object()},
      {'value': Uint8List(1)},
      {
        'value': FormData.fromMap({'field': 'fixture'}),
      },
      {'value': DateTime.utc(2026)},
      {'value': 'x' * (64 * 1024)},
      cycle,
      {
        'nested': {1: 'non-string-key'},
      },
    ]) {
      expect(
        () => mutationEndpoint().createRequest(
          input,
          scope: mutationScope,
          idempotencyKey: mutationKey,
        ),
        throwsA(isA<AppFailure>()),
      );
    }
    final request = mutationEndpoint().createRequest(
      mutationBody(),
      scope: mutationScope,
      idempotencyKey: mutationKey.toUpperCase(),
    );
    expect(request.idempotencyKey, mutationKey);
    expect(jsonDecode(request.encodedBody!), mutationBody());
  });

  test(
    'idempotency is explicit, UUID-only and not a generic header injection',
    () {
      for (final key in [
        null,
        '',
        'not-a-uuid',
        '$mutationKey\r\nAuthorization: private',
        ' $mutationKey',
      ]) {
        expect(
          () => mutationEndpoint().createRequest(
            mutationBody(),
            scope: mutationScope,
            idempotencyKey: key,
          ),
          throwsA(isA<AppFailure>()),
        );
      }
      expect(
        () => mutationEndpoint(idempotent: false).createRequest(
          mutationBody(),
          scope: mutationScope,
          idempotencyKey: mutationKey,
        ),
        throwsA(isA<AppFailure>()),
      );
      for (final status in [199, 202, 206, 299]) {
        expect(
          () => mutationEndpoint(status: status),
          throwsA(isA<AppFailure>()),
        );
      }
    },
  );

  test(
    'a raw mutation 401 ends local scope and never refreshes or replays POST',
    () async {
      final backend = mutationBackend(
        (request) => const OfflineResponse({}, status: 401),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final request = mutationEndpoint().createRequest(
        mutationBody(),
        scope: session.snapshot.key!,
        idempotencyKey: mutationKey,
      );
      final failure = await mutationFailure(session.mutate(request));
      expect(failure.statusCode, 401);
      expect(session.snapshot.key, isNull);
      expect(backend.count('/auth/refresh'), 0);
      expect(backend.count('/payments'), 1);
      await expectLater(session.mutate(request), throwsA(isA<AppFailure>()));
      expect(backend.count('/payments'), 1);
    },
  );
}
