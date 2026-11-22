import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_http.dart';

void main() {
  test('Admin allowed roles are explicit and immutable', () {
    expect(SessionRolePolicy.admin.allowedRoles, {
      'super_admin',
      'warehouse_manager',
      'accountant',
    });
    expect(
      () => SessionRolePolicy.admin.allowedRoles.add('customer'),
      throwsUnsupportedError,
    );
    for (final role in ['customer', 'delivery_partner']) {
      final policy = SessionRolePolicy.exact(role);
      expect(policy.allowedRoles, {role});
      expect(
        () => policy.allowedRoles.add('super_admin'),
        throwsUnsupportedError,
      );
    }
  });

  for (final role in ['super_admin', 'warehouse_manager', 'accountant']) {
    for (final hydrate in [false, true]) {
      test(
        'Admin accepts $role during ${hydrate ? 'hydration' : 'login'}',
        () async {
          final backend = OfflineBackend(
            (request) => request.path == '/auth/login'
                ? OfflineResponse({'user': userJson(role: role)})
                : OfflineResponse(userJson(role: role)),
          );
          final session = SessionController.withRolePolicy(
            config: fixtureConfig(),
            rolePolicy: SessionRolePolicy.admin,
            transportFactory: backend.transport,
          );
          addTearDown(session.dispose);
          if (hydrate) {
            await session.bootstrap();
          } else {
            await session.login('fixture@offline.test', 'fixture-only');
          }
          expect(session.snapshot.isAuthenticated, isTrue);
          expect(session.snapshot.key!.role, role);
          expect(backend.count('/auth/logout'), 0);
        },
      );
    }
  }

  for (final role in ['customer', 'delivery_partner', 'unknown_role']) {
    for (final hydrate in [false, true]) {
      test(
        'Admin excludes $role during ${hydrate ? 'hydration' : 'login'}',
        () async {
          final backend = OfflineBackend(
            (request) => switch (request.path) {
              '/auth/login' => OfflineResponse({
                'user': userJson(role: role),
              }, cookies: sessionCookies('excluded')),
              '/auth/me' => OfflineResponse(userJson(role: role)),
              _ => const OfflineResponse({}),
            },
          );
          final session = SessionController.withRolePolicy(
            config: fixtureConfig(),
            rolePolicy: SessionRolePolicy.admin,
            transportFactory: backend.transport,
          );
          addTearDown(session.dispose);
          if (hydrate) {
            await session.bootstrap();
          } else {
            await expectLater(
              session.login('fixture@offline.test', 'fixture-only'),
              throwsA(isA<AppFailure>()),
            );
          }
          expect(session.snapshot.key, isNull);
          expect(session.snapshot.user, isNull);
          expect(session.snapshot.failure!.kind, FailureKind.wrongRole);
          expect(backend.count('/auth/logout'), 1);
          expect(backend.count('/auth/refresh'), 0);
        },
      );
    }
  }

  test(
    'Admin provider boots with the policy and legacy providers stay exact',
    () async {
      final backend = OfflineBackend(
        (request) => OfflineResponse(userJson(role: 'accountant')),
      );
      final container = ProviderContainer(
        overrides: [
          apiConfigProvider.overrideWithValue(fixtureConfig()),
          sessionTransportFactoryProvider.overrideWithValue(backend.transport),
        ],
      );
      addTearDown(container.dispose);
      expect(
        (await settledSession(container, adminSessionProvider)).key!.role,
        'accountant',
      );
      expect(
        container.read(adminSessionProvider.notifier).rolePolicy,
        SessionRolePolicy.admin,
      );
      for (final role in ['customer', 'delivery_partner']) {
        final provider = roleSessionProvider(role);
        expect(container.read(provider.notifier).expectedRole, role);
        expect(container.read(provider.notifier).rolePolicy.allowedRoles, {
          role,
        });
        await settledSession(container, provider);
        expect(container.read(provider).key, isNull);
      }
    },
  );

  test(
    'an allowed Admin role change during renewal still ends the old identity',
    () async {
      final backend = OfflineBackend(
        (request) => switch (request.path) {
          '/auth/login' => OfflineResponse({
            'user': userJson(role: 'warehouse_manager'),
          }),
          '/auth/me' => OfflineResponse(userJson(role: 'accountant')),
          '/auth/refresh' => const OfflineResponse({}),
          _ => const OfflineResponse({}, status: 401),
        },
      );
      final session = SessionController.withRolePolicy(
        config: fixtureConfig(),
        rolePolicy: SessionRolePolicy.admin,
        transportFactory: backend.transport,
      );
      addTearDown(session.dispose);
      await session.login('fixture@offline.test', 'fixture-only');
      await expectLater(
        session.get('/orders', scope: session.snapshot.key!),
        throwsA(isA<AppFailure>()),
      );
      expect(session.snapshot.key, isNull);
      expect(backend.count('/orders'), 1);
      expect(backend.count('/auth/refresh'), 1);
    },
  );
}
