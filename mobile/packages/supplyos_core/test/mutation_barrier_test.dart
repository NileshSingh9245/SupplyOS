import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'mutation_test.dart';
import 'renewal_barrier_test.dart';
import 'support/offline_http.dart';

void installMutationReply(
  OverlappingRenewals harness,
  FutureOr<OfflineResponse> Function(OfflineRequest) reply,
) {
  final previous = harness.backend.handle;
  harness.backend.handle = (request) =>
      request.path == '/payments' ? reply(request) : previous(request);
}

void main() {
  test('a new mutation waits for held identity verification before its only dispatch', () async {
    final harness = OverlappingRenewals();
    addTearDown(harness.dispose);
    installMutationReply(
      harness,
      (_) => OfflineResponse(mutationReceipt(), status: 201),
    );
    await harness.start();
    final mutation = SessionMutation(
      session: harness.session,
      endpoint: mutationEndpoint(),
    );
    addTearDown(mutation.dispose);
    final attempt = mutation.submit(mutationBody());
    await pumpEventQueue();
    expect(harness.backend.count('/payments'), 0);
    expect(mutation.snapshot.phase, MutationPhase.sending);
    harness.secondIdentity.complete(OfflineResponse(userJson()));
    expect((await attempt).value.text, '1.2300');
    expect(mutation.snapshot.phase, MutationPhase.succeeded);
    expect(harness.backend.count('/payments'), 1);
    expect(harness.backend.count('/auth/refresh'), 2);
    expect(harness.backend.requests.last.cookie.contains('renewal-2'), isTrue);
  });

  for (final changed in [
    ('user', OfflineResponse(userJson(id: userBId))),
    ('tenant', OfflineResponse(userJson(tenantId: tenantBId))),
    ('role', OfflineResponse(userJson(role: 'delivery_partner'))),
    ('revoked', const OfflineResponse({}, status: 401)),
  ]) {
    test(
      'held ${changed.$1} rejection prevents mutation dispatch and invalidates its intent',
      () async {
        final harness = OverlappingRenewals();
        addTearDown(harness.dispose);
        installMutationReply(
          harness,
          (_) => OfflineResponse(mutationReceipt(), status: 201),
        );
        await harness.start();
        final mutation = SessionMutation(
          session: harness.session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        final attempt = captureRead(mutation.submit(mutationBody()));
        await pumpEventQueue();
        expect(harness.backend.count('/payments'), 0);
        harness.secondIdentity.complete(changed.$2);
        expect(await attempt, isA<AppFailure>());
        expect(mutation.snapshot.phase, MutationPhase.invalidated);
        expect(mutation.snapshot.request, isNull);
        expect(mutation.snapshot.response, isNull);
        expect(harness.session.snapshot.key, isNull);
        expect(harness.backend.count('/payments'), 0);
      },
    );
  }

  test(
    'logout while waiting for identity verification prevents dispatch',
    () async {
      final harness = OverlappingRenewals();
      addTearDown(harness.dispose);
      installMutationReply(
        harness,
        (_) => OfflineResponse(mutationReceipt(), status: 201),
      );
      await harness.start();
      final mutation = SessionMutation(
        session: harness.session,
        endpoint: mutationEndpoint(),
      );
      addTearDown(mutation.dispose);
      final attempt = captureRead(mutation.submit(mutationBody()));
      await harness.session.logout();
      harness.secondIdentity.complete(OfflineResponse(userJson()));
      expect(await attempt, isA<AppFailure>());
      expect(mutation.snapshot.phase, MutationPhase.invalidated);
      expect(mutation.snapshot.request, isNull);
      expect(harness.backend.count('/payments'), 0);
    },
  );

  for (final changed in [
    ('same identity', OfflineResponse(userJson())),
    ('different user', OfflineResponse(userJson(id: userBId))),
    ('different tenant', OfflineResponse(userJson(tenantId: tenantBId))),
    ('different role', OfflineResponse(userJson(role: 'delivery_partner'))),
    ('revoked session', const OfflineResponse({}, status: 401)),
  ]) {
    test(
      'in-flight 201 joins a later barrier before publishing ${changed.$1}',
      () async {
        final reply = Completer<OfflineResponse>();
        final harness = OverlappingRenewals();
        addTearDown(harness.dispose);
        installMutationReply(harness, (_) => reply.future);
        await harness.start();
        harness.secondIdentity.complete(OfflineResponse(userJson()));
        await harness.secondRead;
        final mutation = SessionMutation(
          session: harness.session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        final published = <MutationResponse<ServerDecimal>>[];
        final remove = mutation.addListener((next) {
          if (next.response != null) published.add(next.response!);
        });
        addTearDown(remove);
        final attempt = captureRead(mutation.submit(mutationBody()));
        await harness.backend.requested('/payments');
        final third = captureRead(
          harness.session.get('/products', scope: harness.scope),
        );
        await harness.backend.requested('/auth/me', occurrence: 3);
        reply.complete(OfflineResponse(mutationReceipt(), status: 201));
        await pumpEventQueue();
        expect(published, isEmpty);
        expect(mutation.snapshot.response, isNull);
        expect(mutation.snapshot.phase, MutationPhase.sending);
        harness.thirdIdentity.complete(changed.$2);
        final result = await attempt;
        await third;
        if (changed.$1 == 'same identity') {
          expect(result, isA<MutationResponse<ServerDecimal>>());
          expect(published.length, 1);
          expect(mutation.snapshot.phase, MutationPhase.succeeded);
        } else {
          expect(result, isA<AppFailure>());
          expect(published, isEmpty);
          expect(mutation.snapshot.phase, MutationPhase.invalidated);
          expect(mutation.snapshot.request, isNull);
        }
        expect(harness.backend.count('/payments'), 1);
        expect(harness.backend.count('/auth/refresh'), 3);
      },
    );
  }

  for (final rejectIdentity in [false, true]) {
    test(
      'a safe conflict waits for a later ${rejectIdentity ? 'rejected' : 'accepted'} identity barrier',
      () async {
        final reply = Completer<OfflineResponse>();
        final harness = OverlappingRenewals();
        addTearDown(harness.dispose);
        installMutationReply(harness, (_) => reply.future);
        await harness.start();
        harness.secondIdentity.complete(OfflineResponse(userJson()));
        await harness.secondRead;
        final mutation = SessionMutation(
          session: harness.session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        final attempt = captureRead(mutation.submit(mutationBody()));
        await harness.backend.requested('/payments');
        final third = captureRead(
          harness.session.get('/products', scope: harness.scope),
        );
        await harness.backend.requested('/auth/me', occurrence: 3);
        reply.complete(
          const OfflineResponse({'detail': 'private-conflict'}, status: 409),
        );
        await pumpEventQueue();
        expect(mutation.snapshot.failure, isNull);
        expect(mutation.snapshot.phase, MutationPhase.sending);
        harness.thirdIdentity.complete(
          OfflineResponse(rejectIdentity ? userJson(id: userBId) : userJson()),
        );
        expect(await attempt, isA<AppFailure>());
        await third;
        expect(
          mutation.snapshot.phase,
          rejectIdentity ? MutationPhase.invalidated : MutationPhase.rejected,
        );
        if (!rejectIdentity) {
          expect(mutation.snapshot.failure!.kind, FailureKind.conflict);
          expect(
            mutation.snapshot.failure!.message.contains('private-conflict'),
            isFalse,
          );
        }
        expect(harness.backend.count('/payments'), 1);
      },
    );
  }

  for (final rejectIdentity in [false, true]) {
    for (final failsDecode in [false, true]) {
      test(
        'async ${failsDecode ? 'failed' : 'successful'} decode rechecks a later ${rejectIdentity ? 'changed' : 'held'} identity',
        () async {
          final decoding = Completer<void>();
          final decoded = Completer<ServerDecimal>();
          final harness = OverlappingRenewals();
          addTearDown(harness.dispose);
          installMutationReply(
            harness,
            (_) => OfflineResponse(mutationReceipt(), status: 201),
          );
          await harness.start();
          harness.secondIdentity.complete(OfflineResponse(userJson()));
          await harness.secondRead;
          final mutation = SessionMutation(
            session: harness.session,
            endpoint: mutationEndpoint(
              decode: (_, _) {
                decoding.complete();
                return decoded.future;
              },
            ),
          );
          addTearDown(mutation.dispose);
          final attempt = captureRead(mutation.submit(mutationBody()));
          await decoding.future;
          final third = captureRead(
            harness.session.get('/products', scope: harness.scope),
          );
          await harness.backend.requested('/auth/me', occurrence: 3);
          if (failsDecode) {
            decoded.completeError(StateError('private-decoder-input'));
          } else {
            decoded.complete(ServerDecimal.parse('1.2300'));
          }
          await pumpEventQueue();
          expect(mutation.snapshot.response, isNull);
          expect(mutation.snapshot.failure, isNull);
          harness.thirdIdentity.complete(
            OfflineResponse(
              rejectIdentity ? userJson(role: 'delivery_partner') : userJson(),
            ),
          );
          final result = await attempt;
          await third;
          if (rejectIdentity) {
            expect(result, isA<AppFailure>());
            expect(mutation.snapshot.phase, MutationPhase.invalidated);
            expect(mutation.snapshot.request, isNull);
          } else if (failsDecode) {
            expect(result, isA<AppFailure>());
            expect(mutation.snapshot.phase, MutationPhase.uncertain);
            expect(mutation.snapshot.failure!.isOutcomeUncertain, isTrue);
            expect(
              mutation.snapshot.failure!.message.contains(
                'private-decoder-input',
              ),
              isFalse,
            );
          } else {
            expect(result, isA<MutationResponse<ServerDecimal>>());
            expect(mutation.snapshot.phase, MutationPhase.succeeded);
          }
          expect(harness.backend.count('/payments'), 1);
        },
      );
    }
  }

  for (final rejectIdentity in [false, true]) {
    test(
      'explicit same-key retry waits for later ${rejectIdentity ? 'revoked' : 'accepted'} verification',
      () async {
        var succeed = false;
        final harness = OverlappingRenewals();
        addTearDown(harness.dispose);
        installMutationReply(
          harness,
          (_) => succeed
              ? OfflineResponse(mutationReceipt(), status: 201)
              : const OfflineResponse({}, status: 503),
        );
        await harness.start();
        harness.secondIdentity.complete(OfflineResponse(userJson()));
        await harness.secondRead;
        final mutation = SessionMutation(
          session: harness.session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        await mutationFailure(mutation.submit(mutationBody()));
        final original = mutation.snapshot.request!;
        final third = captureRead(
          harness.session.get('/products', scope: harness.scope),
        );
        await harness.backend.requested('/auth/me', occurrence: 3);
        succeed = true;
        final retry = captureRead(mutation.retry());
        await pumpEventQueue();
        expect(harness.backend.count('/payments'), 1);
        harness.thirdIdentity.complete(
          rejectIdentity
              ? const OfflineResponse({}, status: 401)
              : OfflineResponse(userJson()),
        );
        final result = await retry;
        await third;
        if (rejectIdentity) {
          expect(result, isA<AppFailure>());
          expect(mutation.snapshot.phase, MutationPhase.invalidated);
          expect(harness.backend.count('/payments'), 1);
        } else {
          expect(result, isA<MutationResponse<ServerDecimal>>());
          expect(harness.backend.count('/payments'), 2);
          expect(
            harness.backend.requests.last.encodedBody,
            original.encodedBody,
          );
          expect(
            harness.backend.requests.last.options.headers['X-Idempotency-Key'],
            original.idempotencyKey,
          );
          expect(mutation.snapshot.request!.scope, original.scope);
        }
      },
    );
  }

  for (final rejectIdentity in [false, true]) {
    test(
      'reconciliation waits after its lookup and validates ${rejectIdentity ? 'changed' : 'current'} scope',
      () async {
        final lookup = Completer<MutationReconciliation>();
        final started = Completer<void>();
        final harness = OverlappingRenewals();
        addTearDown(harness.dispose);
        installMutationReply(
          harness,
          (_) => const OfflineResponse({}, status: 503),
        );
        await harness.start();
        harness.secondIdentity.complete(OfflineResponse(userJson()));
        await harness.secondRead;
        final mutation = SessionMutation(
          session: harness.session,
          endpoint: mutationEndpoint(),
        );
        addTearDown(mutation.dispose);
        await mutationFailure(mutation.submit(mutationBody()));
        final reconciliation = captureRead(
          mutation.reconcile((_, _) {
            started.complete();
            return lookup.future;
          }),
        );
        await started.future;
        final third = captureRead(
          harness.session.get('/products', scope: harness.scope),
        );
        await harness.backend.requested('/auth/me', occurrence: 3);
        lookup.complete(
          MutationReconciliation.applied(
            statusCode: 201,
            body: mutationReceipt(),
          ),
        );
        await pumpEventQueue();
        expect(mutation.snapshot.response, isNull);
        expect(mutation.snapshot.phase, MutationPhase.reconciling);
        harness.thirdIdentity.complete(
          OfflineResponse(
            rejectIdentity ? userJson(tenantId: tenantBId) : userJson(),
          ),
        );
        final result = await reconciliation;
        await third;
        expect(
          mutation.snapshot.phase,
          rejectIdentity ? MutationPhase.invalidated : MutationPhase.succeeded,
        );
        expect(
          result,
          rejectIdentity
              ? isA<AppFailure>()
              : isA<MutationResponse<ServerDecimal>>(),
        );
        expect(harness.backend.count('/payments'), 1);
      },
    );
  }

  test('logout discards a frozen uncertain intent and a new account cannot replay it', () async {
    var logins = 0;
    final backend = OfflineBackend(
      (request) => switch (request.path) {
        '/auth/login' => OfflineResponse({
          'user': ++logins == 1
              ? userJson()
              : userJson(id: userBId, tenantId: tenantBId),
        }, cookies: sessionCookies('account-$logins')),
        '/auth/logout' => const OfflineResponse({}),
        _ => const OfflineResponse({}, status: 503),
      },
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
    final logout = session.logout();
    expect(mutation.snapshot.phase, MutationPhase.invalidated);
    expect(mutation.snapshot.request, isNull);
    expect(mutation.snapshot.response, isNull);
    await logout;
    await session.login('other@offline.test', 'fixture-only');
    expect(session.snapshot.key!.tenantId, tenantBId);
    expect(() => mutation.retry(), throwsA(isA<AppFailure>()));
    await expectLater(session.mutate(original), throwsA(isA<AppFailure>()));
    expect(backend.count('/payments'), 1);
    await mutationFailure(mutation.submit(mutationBody()));
    expect(mutation.snapshot.request!.scope, session.snapshot.key);
    expect(
      mutation.snapshot.request!.idempotencyKey,
      isNot(original.idempotencyKey),
    );
    expect(backend.requests.last.cookie.contains('account-1'), isFalse);
    expect(backend.count('/payments'), 2);
  });

  test(
    'an in-flight success cannot publish after explicit account replacement',
    () async {
      final oldReply = Completer<OfflineResponse>();
      var logins = 0;
      final backend = OfflineBackend(
        (request) => switch (request.path) {
          '/auth/login' => OfflineResponse({
            'user': ++logins == 1 ? userJson() : userJson(id: userBId),
          }, cookies: sessionCookies('account-$logins')),
          '/payments' => oldReply.future,
          _ => const OfflineResponse({}),
        },
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final mutation = SessionMutation(
        session: session,
        endpoint: mutationEndpoint(),
      );
      addTearDown(mutation.dispose);
      final attempt = captureRead(mutation.submit(mutationBody()));
      final sent = await backend.requested('/payments');
      final original = mutation.snapshot.request!;
      await session.login('other@offline.test', 'fixture-only');
      expect(sent.options.cancelToken!.isCancelled, isTrue);
      oldReply.complete(OfflineResponse(mutationReceipt(), status: 201));
      expect(await attempt, isA<AppFailure>());
      expect(mutation.snapshot.phase, MutationPhase.invalidated);
      expect(mutation.snapshot.request, isNull);
      expect(mutation.snapshot.response, isNull);
      await expectLater(session.mutate(original), throwsA(isA<AppFailure>()));
      expect(backend.count('/payments'), 1);
      expect(session.snapshot.key!.userId, userBId);
    },
  );

  test(
    'equal-value keys from another controller cannot replay an old request',
    () async {
      final backend = mutationBackend(
        (request) => OfflineResponse(mutationReceipt(), status: 201),
      );
      final first = fixtureSession(backend);
      final second = fixtureSession(backend);
      addTearDown(first.dispose);
      addTearDown(second.dispose);
      await first.login('fixture@offline.test', 'fixture-only');
      await second.login('fixture@offline.test', 'fixture-only');
      expect(first.snapshot.key, second.snapshot.key);
      expect(identical(first.snapshot.key, second.snapshot.key), isFalse);
      final original = mutationEndpoint().createRequest(
        mutationBody(),
        scope: first.snapshot.key!,
        idempotencyKey: mutationKey,
      );
      await expectLater(second.mutate(original), throwsA(isA<AppFailure>()));
      expect(backend.count('/payments'), 0);
    },
  );

  test('pre-dispatch cancellation is known, cancellation after dispatch is uncertain', () async {
    final reply = Completer<OfflineResponse>();
    final backend = mutationBackend((request) => reply.future);
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', 'fixture-only');
    final request = mutationEndpoint().createRequest(
      mutationBody(),
      scope: session.snapshot.key!,
      idempotencyKey: mutationKey,
    );
    final before = CancelToken()..cancel('Before dispatch');
    expect(
      (await mutationFailure(session.mutate(request, cancelToken: before)))
          .isOutcomeUncertain,
      isFalse,
    );
    expect(backend.count('/payments'), 0);
    final during = CancelToken();
    final attempt = mutationFailure(
      session.mutate(request, cancelToken: during),
    );
    await backend.requested('/payments');
    during.cancel('After dispatch');
    expect((await attempt).isOutcomeUncertain, isTrue);
    expect(session.snapshot.key, request.scope);
    expect(backend.count('/payments'), 1);
    reply.complete(OfflineResponse(mutationReceipt(), status: 201));
  });

  test(
    'disposing the intent owner prevents delayed decoded publication',
    () async {
      final decoding = Completer<void>();
      final decoded = Completer<ServerDecimal>();
      final backend = mutationBackend(
        (request) => OfflineResponse(mutationReceipt(), status: 201),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      final mutation = SessionMutation(
        session: session,
        endpoint: mutationEndpoint(
          decode: (_, _) {
            decoding.complete();
            return decoded.future;
          },
        ),
      );
      final attempt = captureRead(mutation.submit(mutationBody()));
      await decoding.future;
      mutation.dispose();
      decoded.complete(ServerDecimal.parse('1.2300'));
      expect(await attempt, isA<AppFailure>());
      expect(backend.count('/payments'), 1);
    },
  );
}
