import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_admin/core/intents.dart';
import 'package:supplyos_admin/core/navigation.dart';
import 'package:supplyos_admin/features/catalog.dart';
import 'package:supplyos_admin/features/finance.dart';
import 'package:supplyos_admin/features/staff.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'contracts_test.dart' show productInput, receiptInput;
import 'support/offline_backend.dart';

void main() {
  test('owner navigation matches every supported web destination in order', () {
    expect(destinationsFor(ownerRole).map((item) => item.path), [
      '/dashboard',
      '/inventory',
      '/warehouses',
      '/products',
      '/pricing',
      '/staff',
      '/customers',
      '/orders',
      '/deliveries',
      '/finance',
      '/ai-supervisor',
      '/settings',
    ]);
    expect(homeFor(ownerRole), '/dashboard');
    expect(canVisit(ownerRole, '/audit'), isFalse);
  });
  test('manager navigation and home exactly retain web role filtering', () {
    expect(destinationsFor(managerRole).map((item) => item.path), [
      '/inventory',
      '/warehouses',
      '/products',
      '/pricing',
      '/orders',
      '/deliveries',
    ]);
    expect(homeFor(managerRole), '/inventory');
    expect(canVisit(managerRole, '/finance'), isFalse);
    expect(canVisit(managerRole, '/staff'), isFalse);
    expect(canVisit(managerRole, '/orders/$orderId'), isTrue);
    expect(canVisit(managerRole, '/orders-extra'), isFalse);
  });
  test(
    'accountant navigation and home exclude warehouse/order/staff modules',
    () {
      expect(destinationsFor(accountantRole).map((item) => item.path), [
        '/pricing',
        '/customers',
        '/finance',
      ]);
      expect(homeFor(accountantRole), '/finance');
      for (final path in [
        '/dashboard',
        '/staff',
        '/products',
        '/orders',
        '/deliveries',
        '/inventory',
      ]) {
        expect(canVisit(accountantRole, path), isFalse);
      }
    },
  );
  for (final role in ['customer', 'delivery_partner', 'unknown_role']) {
    test('non-admin $role has no Admin navigation/session access', () async {
      expect(destinationsFor(role), isEmpty);
      expect(canVisit(role, '/intents'), isFalse);
      final backend = OfflineBackend(role: role);
      final session = fixtureSession(backend);
      addTearDown(session.dispose);
      await expectLater(
        session.login('fixture@fixture.test', 'fixture-only'),
        throwsA(
          isA<AppFailure>().having(
            (failure) => failure.kind,
            'kind',
            FailureKind.wrongRole,
          ),
        ),
      );
      expect(session.snapshot.key, isNull);
    });
  }
  for (final role in adminRoles) {
    test('$role is included in explicit Admin policy', () async {
      final session = await signedIn(OfflineBackend(role: role));
      addTearDown(session.dispose);
      expect(session.snapshot.key!.role, role);
    });
  }
  test('accountant cannot write products or staff even through retained registry API', () async {
    final backend = OfflineBackend(role: accountantRole);
    final session = await signedIn(backend);
    addTearDown(session.dispose);
    final registry = AdminIntents(session);
    addTearDown(registry.dispose);
    expect(
      () => registry.submit(productCommand(), productInput),
      throwsA(
        isA<AppFailure>().having(
          (failure) => failure.kind,
          'kind',
          FailureKind.forbidden,
        ),
      ),
    );
    expect(
      () => registry.owner(staffCommand(partnerId)),
      throwsA(isA<AppFailure>()),
    );
    expect(backend.count('/products', 'POST'), 0);
  });
  test(
    'manager cannot allocate payments or discover owner-only staff candidates',
    () async {
      final backend = OfflineBackend(role: managerRole);
      final session = await signedIn(backend);
      addTearDown(session.dispose);
      final registry = AdminIntents(session);
      addTearDown(registry.dispose);
      expect(
        () => registry.submit(paymentCommand, receiptInput),
        throwsA(isA<AppFailure>()),
      );
      expect(backend.count('/payments', 'POST'), 0);
    },
  );
}
