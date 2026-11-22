import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_http.dart';

const fixturePassword = 'offline-fixture-only';

OfflineResponse loginResponse({
  String id = userAId,
  String tenant = tenantAId,
  String role = 'customer',
}) => OfflineResponse({
  'user': userJson(id: id, tenantId: tenant, role: role),
  'access_token': 'unused-json-fixture',
}, cookies: sessionCookies(id));

void main() {
  test(
    'simultaneous 401s perform one cookie renewal and one retry per original',
    () async {
      final renewal = Completer<OfflineResponse>();
      final paths = ['/orders', '/products', '/orders/$orderAId'];
      late OfflineBackend backend;
      backend = OfflineBackend((request) {
        if (request.path == '/auth/login') return loginResponse();
        if (request.path == '/auth/refresh') return renewal.future;
        if (request.path == '/auth/me') return OfflineResponse(userJson());
        if (paths.contains(request.path) && backend.count(request.path) == 1) {
          return const OfflineResponse({'detail': 'fixture'}, status: 401);
        }
        return const OfflineResponse({'ok': true});
      });
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', fixturePassword);
      final key = session.snapshot.key!;
      final reads = [for (final path in paths) session.get(path, scope: key)];
      await backend.requested('/auth/refresh');
      expect(backend.count('/auth/refresh'), 1);
      renewal.complete(
        OfflineResponse({
          'access_token': 'not-used',
        }, cookies: sessionCookies('renewed')),
      );
      await Future.wait(reads);
      expect(backend.count('/auth/refresh'), 1);
      expect(backend.count('/auth/me'), 1);
      for (final path in paths) {
        expect(backend.count(path), 2);
        final replay = backend.requests.lastWhere(
          (request) => request.path == path,
        );
        expect(replay.cookie.contains('fixture-access-renewed'), isTrue);
        expect(replay.options.headers.containsKey('Authorization'), isFalse);
      }
      final refresh = backend.requests.singleWhere(
        (request) => request.path == '/auth/refresh',
      );
      expect(refresh.cookie.contains('fixture-refresh-'), isTrue);
      expect(refresh.body, isNull);
      expect(session.snapshot.key, key);
    },
  );

  test(
    'a slow old-token 401 skips the renewal already completed by its peer',
    () async {
      final slowResponse = Completer<OfflineResponse>();
      late OfflineBackend backend;
      backend = OfflineBackend((request) {
        switch (request.path) {
          case '/auth/login':
            return loginResponse();
          case '/auth/me':
            return OfflineResponse(userJson());
          case '/auth/refresh':
            return OfflineResponse({}, cookies: sessionCookies('renewed'));
          case '/orders':
            return backend.count('/orders') == 1
                ? const OfflineResponse({}, status: 401)
                : const OfflineResponse({'ok': true});
          case '/products':
            return backend.count('/products') == 1
                ? slowResponse.future
                : const OfflineResponse({'ok': true});
          default:
            return const OfflineResponse({});
        }
      });
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', fixturePassword);
      final key = session.snapshot.key!;
      final fast = session.get('/orders', scope: key);
      final slow = session.get('/products', scope: key);
      await backend.requested('/products');
      await fast;
      slowResponse.complete(const OfflineResponse({}, status: 401));
      await slow;
      expect(backend.count('/auth/refresh'), 1);
      expect(backend.count('/orders'), 2);
      expect(backend.count('/products'), 2);
    },
  );

  test('bootstrap /me renews once and retries the original /me once', () async {
    late OfflineBackend backend;
    backend = OfflineBackend((request) {
      if (request.path == '/auth/refresh') {
        return OfflineResponse({}, cookies: sessionCookies('bootstrap'));
      }
      if (request.path == '/auth/me') {
        return backend.count('/auth/me') == 1
            ? const OfflineResponse({}, status: 401)
            : OfflineResponse(userJson());
      }
      return const OfflineResponse({});
    });
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.bootstrap();
    expect(session.snapshot.isAuthenticated, isTrue);
    expect(backend.count('/auth/me'), 2);
    expect(backend.count('/auth/refresh'), 1);
    await session.bootstrap();
    expect(backend.count('/auth/me'), 2);
  });

  test(
    'bootstrap terminal refresh 401 is nonrecursive and remains signed out',
    () async {
      final backend = OfflineBackend(
        (request) => const OfflineResponse({}, status: 401),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.bootstrap();
      expect(session.snapshot.key, isNull);
      expect(session.snapshot.phase, SessionPhase.signedOut);
      expect(backend.count('/auth/me'), 1);
      expect(backend.count('/auth/refresh'), 1);
      expect(backend.count('/auth/logout'), 0);
    },
  );

  test('401 on the retry is terminal, never a second refresh', () async {
    final backend = OfflineBackend((request) {
      if (request.path == '/auth/login') return loginResponse();
      if (request.path == '/auth/refresh') return const OfflineResponse({});
      if (request.path == '/auth/me') return OfflineResponse(userJson());
      return const OfflineResponse({}, status: 401);
    });
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', fixturePassword);
    await expectLater(
      session.get('/orders', scope: session.snapshot.key!),
      throwsA(isA<AppFailure>()),
    );
    expect(backend.count('/orders'), 2);
    expect(backend.count('/auth/refresh'), 1);
    expect(session.snapshot.key, isNull);
  });

  for (final status in [401, 403, 503]) {
    test('renewal failure $status clears the session without replay', () async {
      final backend = OfflineBackend((request) {
        if (request.path == '/auth/login') return loginResponse();
        if (request.path == '/auth/refresh') {
          return OfflineResponse({}, status: status);
        }
        return const OfflineResponse({}, status: 401);
      });
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', fixturePassword);
      await expectLater(
        session.get('/orders', scope: session.snapshot.key!),
        throwsA(isA<AppFailure>()),
      );
      expect(session.snapshot.key, isNull);
      expect(session.snapshot.user, isNull);
      expect(backend.count('/orders'), 1);
      expect(backend.count('/auth/refresh'), 1);
      expect(backend.count('/auth/me'), 0);
      expect(backend.count('/auth/logout'), 0);
    });
  }

  test(
    'login 401 never refreshes and cannot expose server error details',
    () async {
      final backend = OfflineBackend(
        (request) => const OfflineResponse({
          'detail': 'untrusted-fixture-detail',
        }, status: 401),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await expectLater(
        session.login('fixture@offline.test', fixturePassword),
        throwsA(
          isA<AppFailure>().having(
            (error) => error.kind,
            'kind',
            FailureKind.invalidCredentials,
          ),
        ),
      );
      expect(backend.count('/auth/refresh'), 0);
      expect(session.snapshot.failure!.message.contains('untrusted'), isFalse);
      expect(
        session.snapshot.failure!.message.contains(fixturePassword),
        isFalse,
      );
    },
  );

  test(
    'logout clears local identity immediately even if server logout fails',
    () async {
      final reply = Completer<OfflineResponse>();
      final backend = OfflineBackend((request) {
        if (request.path == '/auth/login') return loginResponse();
        if (request.path == '/auth/logout') return reply.future;
        return const OfflineResponse({});
      });
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', fixturePassword);
      final scope = session.snapshot.key!;
      final logout = session.logout();
      expect(session.snapshot.key, isNull);
      expect(session.snapshot.user, isNull);
      await expectLater(
        session.get('/orders', scope: scope),
        throwsA(isA<AppFailure>()),
      );
      await backend.requested('/auth/logout');
      reply.complete(const OfflineResponse({}, status: 503));
      expect(await logout, LogoutOutcome.unconfirmed);
      expect(session.snapshot.logoutOutcome, LogoutOutcome.unconfirmed);
      expect(backend.count('/auth/refresh'), 0);
      await session.bootstrap();
      expect(backend.count('/auth/me'), 0);
    },
  );

  test(
    'logout 401 is not refreshed or reported as confirmed revocation',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? loginResponse()
            : const OfflineResponse({}, status: 401),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', fixturePassword);
      expect(await session.logout(), LogoutOutcome.unconfirmed);
      expect(backend.count('/auth/refresh'), 0);
    },
  );

  test(
    'a delayed login response cannot resurrect a logged-out session',
    () async {
      final reply = Completer<OfflineResponse>();
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? reply.future
            : const OfflineResponse({}),
      );
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      final login = session.login('fixture@offline.test', fixturePassword);
      final rejected = expectLater(login, throwsA(isA<AppFailure>()));
      await backend.requested('/auth/login');
      await session.logout();
      reply.complete(loginResponse());
      await rejected;
      expect(session.snapshot.key, isNull);
      expect(session.snapshot.isAuthenticated, isFalse);
    },
  );

  test(
    'a delayed bootstrap cannot replace a newer explicit login identity',
    () async {
      final reply = Completer<OfflineResponse>();
      final backend = OfflineBackend((request) {
        if (request.path == '/auth/me') return reply.future;
        if (request.path == '/auth/login') {
          return loginResponse(id: userBId, tenant: tenantBId);
        }
        return const OfflineResponse({});
      });
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      final bootstrap = session.bootstrap();
      await backend.requested('/auth/me');
      await session.login('fixture-b@offline.test', fixturePassword);
      reply.complete(
        OfflineResponse(userJson(), cookies: sessionCookies('old')),
      );
      await bootstrap;
      expect(session.snapshot.user!.id, userBId);
      expect(session.snapshot.user!.tenantId, tenantBId);
    },
  );

  test('a delayed refresh/read cannot resurrect logout or contaminate the next account', () async {
    final renewal = Completer<OfflineResponse>();
    var loginCount = 0;
    final backend = OfflineBackend((request) {
      if (request.path == '/auth/login') {
        return loginResponse(id: ++loginCount == 1 ? userAId : userBId);
      }
      if (request.path == '/auth/refresh') return renewal.future;
      if (request.path == '/orders') {
        return const OfflineResponse({}, status: 401);
      }
      if (request.path == '/auth/logout') return const OfflineResponse({});
      return const OfflineResponse({'ok': true});
    });
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture-a@offline.test', fixturePassword);
    final read = session.get('/orders', scope: session.snapshot.key!);
    final rejected = expectLater(read, throwsA(isA<AppFailure>()));
    await backend.requested('/auth/refresh');
    await session.logout();
    await session.login('fixture-b@offline.test', fixturePassword);
    renewal.complete(
      OfflineResponse({}, cookies: sessionCookies('old-renewal')),
    );
    await rejected;
    await session.get('/products', scope: session.snapshot.key!);
    expect(session.snapshot.user!.id, userBId);
    final request = backend.requests.last;
    expect(request.cookie.contains('old-renewal'), isFalse);
    expect(request.cookie.contains(userAId), isFalse);
    expect(request.cookie.contains(userBId), isTrue);
    expect(backend.count('/orders'), 1);
  });

  test('new login waits for older logout and is not cleared by its delayed completion', () async {
    final logoutReply = Completer<OfflineResponse>();
    var logins = 0;
    final backend = OfflineBackend((request) {
      if (request.path == '/auth/login') {
        return loginResponse(id: ++logins == 1 ? userAId : userBId);
      }
      if (request.path == '/auth/logout') return logoutReply.future;
      return const OfflineResponse({});
    });
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture-a@offline.test', fixturePassword);
    final logout = session.logout();
    await backend.requested('/auth/logout');
    final login = session.login('fixture-b@offline.test', fixturePassword);
    expect(backend.count('/auth/login'), 1);
    expect(session.snapshot.key, isNull);
    logoutReply.complete(const OfflineResponse({}));
    expect(await logout, LogoutOutcome.confirmed);
    await login;
    expect(session.snapshot.user!.id, userBId);
    expect(session.snapshot.logoutOutcome, isNull);
  });

  for (final expected in ['customer', 'delivery_partner']) {
    for (final role in [
      'super_admin',
      'warehouse_manager',
      'accountant',
      expected == 'customer' ? 'delivery_partner' : 'customer',
      'unknown_role',
    ]) {
      test('$expected rejects $role at login and purges cookies', () async {
        final backend = OfflineBackend(
          (request) => request.path == '/auth/login'
              ? loginResponse(role: role)
              : const OfflineResponse({}),
        );
        final session = fixtureSession(backend, role: expected);
        addTearDown(session.dispose);
        await expectLater(
          session.login('fixture@offline.test', fixturePassword),
          throwsA(
            isA<AppFailure>().having(
              (error) => error.kind,
              'kind',
              FailureKind.wrongRole,
            ),
          ),
        );
        expect(session.snapshot.key, isNull);
        expect(backend.count('/auth/logout'), 1);
        expect(backend.count('/auth/refresh'), 0);
      });

      test(
        '$expected rejects $role at hydration without publishing identity',
        () async {
          final backend = OfflineBackend(
            (request) => request.path == '/auth/me'
                ? OfflineResponse(
                    userJson(role: role),
                    cookies: sessionCookies('wrong-role'),
                  )
                : const OfflineResponse({}),
          );
          final session = fixtureSession(backend, role: expected);
          addTearDown(session.dispose);
          await session.bootstrap();
          expect(session.snapshot.key, isNull);
          expect(session.snapshot.user, isNull);
          expect(session.snapshot.failure!.kind, FailureKind.wrongRole);
          expect(backend.count('/auth/logout'), 1);
          expect(backend.count('/auth/refresh'), 0);
        },
      );
    }
  }

  for (final changed in [
    userJson(id: userBId),
    userJson(tenantId: tenantBId),
    userJson(role: 'delivery_partner'),
  ].indexed) {
    test(
      'identity change ${changed.$1 + 1} during renewal cancels original read',
      () async {
        final backend = OfflineBackend((request) {
          if (request.path == '/auth/login') return loginResponse();
          if (request.path == '/auth/refresh') return const OfflineResponse({});
          if (request.path == '/auth/me') return OfflineResponse(changed.$2);
          return const OfflineResponse({}, status: 401);
        });
        final session = fixtureSession(backend);
        addTearDown(session.dispose);
        await session.login('fixture@offline.test', fixturePassword);
        await expectLater(
          session.get('/orders', scope: session.snapshot.key!),
          throwsA(isA<AppFailure>()),
        );
        expect(session.snapshot.key, isNull);
        expect(backend.count('/orders'), 1);
      },
    );
  }

  test('verification /me 401 after refresh never recursively renews', () async {
    final backend = OfflineBackend((request) {
      if (request.path == '/auth/login') return loginResponse();
      if (request.path == '/auth/refresh') return const OfflineResponse({});
      return const OfflineResponse({}, status: 401);
    });
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', fixturePassword);
    await expectLater(
      session.get('/orders', scope: session.snapshot.key!),
      throwsA(isA<AppFailure>()),
    );
    expect(backend.count('/auth/refresh'), 1);
    expect(backend.count('/auth/me'), 1);
    expect(backend.count('/orders'), 1);
  });

  test('bootstrap connection failure is visible and a deliberate retry can recover', () async {
    var available = false;
    final backend = OfflineBackend(
      (request) => available
          ? OfflineResponse(userJson())
          : const OfflineResponse({}, status: 503),
    );
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.bootstrap();
    expect(session.snapshot.phase, SessionPhase.checkFailed);
    expect(session.snapshot.failure!.kind, FailureKind.server);
    available = true;
    await session.retryBootstrap();
    expect(session.snapshot.isAuthenticated, isTrue);
    expect(backend.count('/auth/me'), 2);
  });

  test('configuration absence disables transport and sign-in', () async {
    var created = 0;
    final session = SessionController(
      config: null,
      expectedRole: 'customer',
      transportFactory: (config) {
        created++;
        throw StateError('Must not create transport');
      },
    );
    addTearDown(session.dispose);
    await session.bootstrap();
    await expectLater(
      session.login('fixture@offline.test', fixturePassword),
      throwsA(isA<AppFailure>()),
    );
    expect(created, 0);
    expect(session.snapshot.phase, SessionPhase.unavailable);
  });

  test(
    'disposing a controller cancels pending login and cannot publish its reply',
    () async {
      final reply = Completer<OfflineResponse>();
      final backend = OfflineBackend((request) => reply.future);
      final session = fixtureSession(backend);
      final login = session.login('fixture@offline.test', fixturePassword);
      final rejected = expectLater(login, throwsA(isA<AppFailure>()));
      await backend.requested('/auth/login');
      session.dispose();
      reply.complete(loginResponse());
      await rejected;
      expect(backend.adapters.every((adapter) => adapter.isClosed), isTrue);
    },
  );

  test('transport construction failure fails closed without an unhandled bootstrap', () async {
    final session = SessionController(
      config: fixtureConfig(),
      expectedRole: 'customer',
      transportFactory: (config) => throw StateError('offline fixture failure'),
    );
    addTearDown(session.dispose);
    await session.bootstrap();
    expect(session.snapshot.phase, SessionPhase.unavailable);
    expect(session.snapshot.key, isNull);
    expect(session.snapshot.failure!.kind, FailureKind.configuration);
  });

  test('a completed failed logout does not poison the next account logout acknowledgement', () async {
    var failLogout = true;
    final backend = OfflineBackend(
      (request) => request.path == '/auth/login'
          ? loginResponse()
          : OfflineResponse({}, status: failLogout ? 503 : 200),
    );
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', fixturePassword);
    expect(await session.logout(), LogoutOutcome.unconfirmed);
    failLogout = false;
    await session.login('fixture@offline.test', fixturePassword);
    expect(await session.logout(), LogoutOutcome.confirmed);
  });
}
