import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_http.dart';

Future<Object?> captureRead(Future<Object?> read) => read.then<Object?>(
  (data) => data,
  onError: (Object error, StackTrace stack) => AppFailure.safe(error),
);

class OverlappingRenewals {
  OverlappingRenewals({this.pauseDecode = false}) {
    backend = OfflineBackend((request) {
      switch (request.path) {
        case '/auth/login':
          return OfflineResponse({
            'user': userJson(),
          }, cookies: sessionCookies('login'));
        case '/auth/logout':
          return const OfflineResponse({});
        case '/auth/refresh':
          return OfflineResponse(
            {},
            cookies: sessionCookies(
              'renewal-${backend.count('/auth/refresh')}',
            ),
          );
        case '/auth/me':
          return switch (backend.count('/auth/me')) {
            1 => OfflineResponse(userJson()),
            2 => secondIdentity.future,
            _ => thirdIdentity.future,
          };
        case '/orders':
          return backend.count('/orders') == 1
              ? delayedRead.future
              : const OfflineResponse({'name': 'Scoped result'});
        case '/products':
          return backend.count('/products').isOdd
              ? const OfflineResponse({}, status: 401)
              : const OfflineResponse({});
        case '/orders/$orderAId':
          return backend.count(request.path) == 1
              ? const OfflineResponse({}, status: 401)
              : const OfflineResponse({});
        default:
          throw StateError('Unexpected offline fixture request');
      }
    });
    session = fixtureSession(backend);
    final auth = StateNotifierProvider<SessionController, SessionState>(
      (ref) => session,
    );
    container = ProviderContainer();
    query = SessionQuery<String, int>(
      sessionProvider: auth,
      load: (session, scope, argument, token) async {
        final response = await session.get(
          '/orders',
          scope: scope,
          cancelToken: token,
        );
        if (!received.isCompleted) received.complete();
        if (pauseDecode) await decoded.future;
        return JsonObject(response).string('name');
      },
    );
    subscription = container.listen(query.provider(0), (_, next) {
      if (next.asData != null) published.add(next.requireValue);
    }, fireImmediately: true);
  }

  final bool pauseDecode;
  final delayedRead = Completer<OfflineResponse>();
  final secondIdentity = Completer<OfflineResponse>();
  final thirdIdentity = Completer<OfflineResponse>();
  final received = Completer<void>();
  final decoded = Completer<void>();
  final published = <String>[];
  late final OfflineBackend backend;
  late final SessionController session;
  late final ProviderContainer container;
  late final SessionQuery<String, int> query;
  late final ProviderSubscription<AsyncValue<String>> subscription;
  late final SessionKey scope;
  late final Future<Object?> secondRead;

  Future<void> start() async {
    await session.login('fixture@offline.test', 'fixture-password');
    scope = session.snapshot.key!;
    await backend.requested('/orders');
    await session.get('/products', scope: scope);
    expect(backend.count('/auth/refresh'), 1);
    expect(backend.count('/auth/me'), 1);
    secondRead = captureRead(session.get('/orders/$orderAId', scope: scope));
    await backend.requested('/auth/me', occurrence: 2);
  }

  void releaseRead({bool successful = false}) => delayedRead.complete(
    successful
        ? const OfflineResponse({'name': 'Scoped result'})
        : const OfflineResponse({}, status: 401),
  );

  void expectNoPublication() {
    expect(published, isEmpty);
    expect(container.read(query.provider(0)).asData, isNull);
  }

  void dispose() {
    subscription.close();
    container.dispose();
    if (!delayedRead.isCompleted) releaseRead();
    if (!secondIdentity.isCompleted) {
      secondIdentity.complete(OfflineResponse(userJson()));
    }
    if (!thirdIdentity.isCompleted) {
      thirdIdentity.complete(OfflineResponse(userJson()));
    }
    if (!decoded.isCompleted) decoded.complete();
  }
}

void main() {
  test('late 401 joins a second identity barrier without replay or publication before verification', () async {
    final harness = OverlappingRenewals();
    addTearDown(harness.dispose);
    await harness.start();
    harness.releaseRead();
    await pumpEventQueue();
    expect(harness.backend.count('/orders'), 1);
    expect(harness.backend.count('/orders/$orderAId'), 1);
    harness.expectNoPublication();
    harness.secondIdentity.complete(OfflineResponse(userJson()));
    expect(await harness.secondRead, isNot(isA<AppFailure>()));
    expect(
      (await settledQuery(
        harness.container,
        harness.query.provider(0),
      )).requireValue,
      'Scoped result',
    );
    expect(harness.backend.count('/orders'), 2);
    expect(harness.backend.count('/auth/refresh'), 2);
    expect(harness.backend.count('/auth/me'), 2);
    expect(harness.session.snapshot.key, harness.scope);
  });

  for (final change in [
    ('user', userJson(id: userBId)),
    ('tenant', userJson(tenantId: tenantBId)),
    ('role', userJson(role: 'delivery_partner')),
  ]) {
    test(
      'second identity barrier rejects changed ${change.$1} without delayed replay or cache publication',
      () async {
        final harness = OverlappingRenewals();
        addTearDown(harness.dispose);
        await harness.start();
        harness.releaseRead();
        await pumpEventQueue();
        expect(harness.backend.count('/orders'), 1);
        harness.expectNoPublication();
        harness.secondIdentity.complete(OfflineResponse(change.$2));
        expect(await harness.secondRead, isA<AppFailure>());
        expect(
          (await settledQuery(
            harness.container,
            harness.query.provider(0),
          )).error,
          isA<AppFailure>(),
        );
        await pumpEventQueue();
        harness.expectNoPublication();
        expect(harness.session.snapshot.key, isNull);
        expect(harness.backend.count('/orders'), 1);
        expect(harness.backend.count('/orders/$orderAId'), 1);
        expect(harness.backend.count('/auth/refresh'), 2);
      },
    );
  }

  test('logout cancels second identity barrier waiters without replay or cache publication', () async {
    final harness = OverlappingRenewals();
    addTearDown(harness.dispose);
    await harness.start();
    harness.releaseRead();
    await pumpEventQueue();
    expect(harness.backend.count('/orders'), 1);
    harness.expectNoPublication();
    await harness.session.logout();
    expect(await harness.secondRead, isA<AppFailure>());
    harness.secondIdentity.complete(OfflineResponse(userJson()));
    await pumpEventQueue();
    harness.expectNoPublication();
    expect(harness.session.snapshot.key, isNull);
    expect(harness.backend.count('/orders'), 1);
    expect(harness.backend.count('/orders/$orderAId'), 1);
  });

  for (final rejected in [false, true]) {
    test(
      'in-flight 200 waits for second verification before ${rejected ? 'identity rejection' : 'publication'}',
      () async {
        final harness = OverlappingRenewals();
        addTearDown(harness.dispose);
        await harness.start();
        harness.releaseRead(successful: true);
        await pumpEventQueue();
        harness.expectNoPublication();
        harness.secondIdentity.complete(
          OfflineResponse(
            rejected ? userJson(tenantId: tenantBId) : userJson(),
          ),
        );
        final value = await settledQuery(
          harness.container,
          harness.query.provider(0),
        );
        if (rejected) {
          expect(await harness.secondRead, isA<AppFailure>());
          expect(value.error, isA<AppFailure>());
          harness.expectNoPublication();
        } else {
          expect(await harness.secondRead, isNot(isA<AppFailure>()));
          expect(value.requireValue, 'Scoped result');
        }
        expect(harness.backend.count('/orders'), 1);
        expect(harness.backend.count('/auth/refresh'), 2);
      },
    );
  }

  for (final rejected in [false, true]) {
    test(
      'async decoding joins a later third barrier before ${rejected ? 'role rejection' : 'publication'}',
      () async {
        final harness = OverlappingRenewals(pauseDecode: true);
        addTearDown(harness.dispose);
        await harness.start();
        harness.releaseRead();
        harness.secondIdentity.complete(OfflineResponse(userJson()));
        expect(await harness.secondRead, isNot(isA<AppFailure>()));
        await harness.received.future;
        final thirdRead = captureRead(
          harness.session.get('/products', scope: harness.scope),
        );
        await harness.backend.requested('/auth/me', occurrence: 3);
        harness.decoded.complete();
        await pumpEventQueue();
        harness.expectNoPublication();
        harness.thirdIdentity.complete(
          OfflineResponse(
            rejected ? userJson(role: 'delivery_partner') : userJson(),
          ),
        );
        final value = await settledQuery(
          harness.container,
          harness.query.provider(0),
        );
        if (rejected) {
          expect(await thirdRead, isA<AppFailure>());
          expect(value.error, isA<AppFailure>());
          harness.expectNoPublication();
        } else {
          expect(await thirdRead, isNot(isA<AppFailure>()));
          expect(value.requireValue, 'Scoped result');
        }
        expect(harness.backend.count('/auth/refresh'), 3);
        expect(harness.backend.count('/auth/me'), 3);
      },
    );
  }
}
