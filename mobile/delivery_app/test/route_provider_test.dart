import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_delivery/features/auth/auth_provider.dart';
import 'package:supplyos_delivery/features/route/route_provider.dart';
import 'package:supplyos_delivery/main.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import 'support/delivery_fixtures.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
      'route requests are authenticated GETs with no caller-selected partner or tenant',
      () async {
    final harness =
        DeliveryHarness((request) async => OfflineResponse([stopJson()]));
    addTearDown(harness.dispose);
    expect(harness.container.read(routeProvider(null)).asData, isNull);
    expect(harness.backend.requests, isEmpty);
    await harness.login();
    final value = await settledQuery(harness.container, routeProvider(null));
    expect(value.requireValue.single.orderId, orderAId);
    final request = harness.backend.requests.last;
    expect(request.path, '/deliveries/my-route');
    expect(request.method, 'GET');
    expect(request.body, isNull);
    expect(request.options.queryParameters, isEmpty);
  });

  test('route cache clears at logout and scopes to the next user and tenant',
      () async {
    final harness = DeliveryHarness((request) async => OfflineResponse([
          stopJson(
              orderId: request.cookie.contains(userBId) ? orderBId : orderAId),
        ]));
    addTearDown(harness.dispose);
    await harness.login();
    final keep = harness.container.listen(routeProvider(null), (_, next) {});
    addTearDown(keep.close);
    expect(
        (await settledQuery(harness.container, routeProvider(null)))
            .requireValue
            .single
            .orderId,
        orderAId);
    final old = harness.session.snapshot.key!;
    final logout = harness.session.logout();
    expect(harness.container.read(routeProvider(null)).asData, isNull);
    await logout;
    await harness.login(accountB: true);
    expect(harness.session.snapshot.key, isNot(old));
    expect(harness.container.read(routeProvider(null)).asData, isNull);
    expect(
        (await settledQuery(harness.container, routeProvider(null)))
            .requireValue
            .single
            .orderId,
        orderBId);
  });

  test('a delayed route reply cannot restore data after account switching',
      () async {
    final oldReply = Completer<OfflineResponse>();
    final harness = DeliveryHarness((request) async =>
        request.cookie.contains(userAId)
            ? await oldReply.future
            : OfflineResponse([stopJson(orderId: orderBId)]));
    addTearDown(harness.dispose);
    await harness.login();
    final keep = harness.container.listen(routeProvider(null), (_, next) {});
    addTearDown(keep.close);
    final old = await harness.backend.requested('/deliveries/my-route');
    await harness.session.logout();
    expect(old.options.cancelToken!.isCancelled, isTrue);
    await harness.login(accountB: true);
    expect(
        (await settledQuery(harness.container, routeProvider(null)))
            .requireValue
            .single
            .orderId,
        orderBId);
    oldReply.complete(OfflineResponse([stopJson()]));
    await harness.container.pump();
    expect(
        harness.container.read(routeProvider(null)).requireValue.single.orderId,
        orderBId);
  });

  for (final role in ['super_admin', 'warehouse_manager', 'customer']) {
    test('delivery app rejects $role during hydration and login', () async {
      final backend = OfflineBackend((request) => request.path == '/auth/me'
          ? OfflineResponse(userJson(role: role))
          : request.path == '/auth/login'
              ? OfflineResponse({'user': userJson(role: role)})
              : const OfflineResponse({}));
      final container = ProviderContainer(overrides: [
        apiConfigProvider.overrideWithValue(fixtureConfig()),
        sessionTransportFactoryProvider.overrideWithValue(backend.transport),
      ]);
      addTearDown(container.dispose);
      final state = await settledSession(container, authProvider);
      expect(state.key, isNull);
      expect(state.failure!.kind, FailureKind.wrongRole);
      expect(container.read(authProvider.notifier).expectedRole,
          'delivery_partner');
      await expectLater(
          container
              .read(authProvider.notifier)
              .login('fixture@offline.test', 'fixture-password'),
          throwsA(isA<AppFailure>()
              .having((error) => error.kind, 'kind', FailureKind.wrongRole)));
      expect(backend.count('/auth/refresh'), 0);
    });
  }

  test(
      'delivery router is stable across session transitions and disposed by its owner',
      () async {
    final harness =
        DeliveryHarness((request) async => const OfflineResponse(<Object?>[]));
    final router = harness.container.read(routerProvider);
    await harness.login();
    expect(identical(router, harness.container.read(routerProvider)), isTrue);
    await harness.session.logout();
    expect(identical(router, harness.container.read(routerProvider)), isTrue);
    harness.dispose();
  });
}
