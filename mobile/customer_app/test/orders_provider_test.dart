import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_customer/features/auth/auth_provider.dart';
import 'package:supplyos_customer/features/catalog/catalog_provider.dart';
import 'package:supplyos_customer/features/orders/orders_provider.dart';
import 'package:supplyos_customer/main.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import 'support/customer_fixtures.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('orders, detail, history and catalog issue only scoped GET contracts',
      () async {
    final harness = CustomerHarness((request) async {
      if (request.path == '/orders') {
        return OfflineResponse(pageJson([orderJson()]));
      }
      if (request.path == '/catalog') {
        return OfflineResponse(pageJson([productJson()]));
      }
      if (request.path.endsWith('/history')) {
        return OfflineResponse([historyJson()]);
      }
      return OfflineResponse(orderJson());
    });
    addTearDown(harness.dispose);
    await harness.login();
    final orders = await settledQuery(harness.container, ordersProvider(1));
    final detail =
        await settledQuery(harness.container, orderQuery.provider(orderAId));
    final history = await settledQuery(
        harness.container, orderHistoryQuery.provider(orderAId));
    final catalog = await settledQuery(harness.container, productsProvider(1));
    expect(orders.requireValue.items.single.id, orderAId);
    expect(detail.requireValue.id, orderAId);
    expect(history.requireValue.length, 1);
    expect(catalog.requireValue.items.single.price.text, '41.80');
    final reads = harness.backend.requests
        .where((request) => !request.path.startsWith('/auth/'));
    for (final request in reads) {
      expect(request.method, 'GET');
      expect(request.body, isNull);
      if (request.path == '/orders' || request.path == '/catalog') {
        expect(request.options.queryParameters, {'page': 1, 'page_size': 50});
      } else {
        expect(request.options.queryParameters, isEmpty);
      }
      expect(
          request.options.queryParameters.containsKey('customer_id'), isFalse);
      expect(request.options.queryParameters.containsKey('tenant_id'), isFalse);
      expect(
          request.options.queryParameters.containsKey('warehouse_id'), isFalse);
    }
  });

  test(
      'all customer caches and pagination scope clear immediately across accounts',
      () async {
    final harness = CustomerHarness((request) async {
      final isB = request.cookie.contains(userBId);
      final id = isB ? orderBId : orderAId;
      if (request.path == '/orders') {
        return OfflineResponse(
            pageJson([orderJson(id: id, number: isB ? 'ORD-B' : 'ORD-A')]));
      }
      if (request.path == '/catalog') {
        return OfflineResponse(
            pageJson([productJson(name: isB ? 'Product B' : 'Product A')]));
      }
      if (request.path.endsWith('/history')) {
        return OfflineResponse(
            [historyJson(note: isB ? 'History B' : 'History A')]);
      }
      return OfflineResponse(orderJson(id: id));
    });
    addTearDown(harness.dispose);
    await harness.login();
    final container = harness.container;
    final keeps = [
      container.listen(ordersProvider(1), (_, next) {}),
      container.listen(productsProvider(1), (_, next) {}),
      container.listen(orderQuery.provider(orderAId), (_, next) {}),
      container.listen(orderHistoryQuery.provider(orderAId), (_, next) {}),
    ];
    addTearDown(() {
      for (final keep in keeps) {
        keep.close();
      }
    });
    await settledQuery(container, ordersProvider(1));
    await settledQuery(container, productsProvider(1));
    await settledQuery(container, orderQuery.provider(orderAId));
    await settledQuery(container, orderHistoryQuery.provider(orderAId));
    final old = harness.session.snapshot.key!;
    final pageKeep = container.listen(ordersPageProvider(old), (_, next) {});
    addTearDown(pageKeep.close);
    container.read(ordersPageProvider(old).notifier).state = 2;
    final logout = harness.session.logout();
    expect(container.read(ordersProvider(1)).asData, isNull);
    expect(container.read(productsProvider(1)).asData, isNull);
    expect(container.read(orderQuery.provider(orderAId)).asData, isNull);
    expect(container.read(orderHistoryQuery.provider(orderAId)).asData, isNull);
    await logout;
    await harness.login(accountB: true);
    expect(container.read(ordersProvider(1)).asData, isNull);
    expect(
        (await settledQuery(container, ordersProvider(1)))
            .requireValue
            .items
            .single
            .orderNumber,
        'ORD-B');
    expect(
        (await settledQuery(container, productsProvider(1)))
            .requireValue
            .items
            .single
            .name,
        'Product B');
    expect(
        (await settledQuery(container, orderQuery.provider(orderBId)))
            .requireValue
            .id,
        orderBId);
    expect(
        (await settledQuery(container, orderHistoryQuery.provider(orderBId)))
            .requireValue
            .single
            .note,
        'History B');
    expect(
        container.read(ordersPageProvider(harness.session.snapshot.key!)), 1);
  });

  test(
      'malformed detail identifiers never reach HTTP and mismatched returned IDs fail closed',
      () async {
    final harness = CustomerHarness(
        (request) async => OfflineResponse(orderJson(id: orderBId)));
    addTearDown(harness.dispose);
    await harness.login();
    expect(
        (await settledQuery(
                harness.container, orderQuery.provider('not-a-uuid')))
            .error,
        isA<AppFailure>());
    expect(
        (await settledQuery(
                harness.container, orderHistoryQuery.provider('../auth/me')))
            .error,
        isA<AppFailure>());
    expect(harness.backend.count('/orders/not-a-uuid'), 0);
    final mismatch =
        await settledQuery(harness.container, orderQuery.provider(orderAId));
    expect(mismatch.error, isA<AppFailure>());
  });

  test(
      'orders rejects malformed or mismatched pagination instead of assuming defaults',
      () async {
    final harness = CustomerHarness(
        (request) async => OfflineResponse(pageJson([orderJson()], page: 2)));
    addTearDown(harness.dispose);
    await harness.login();
    final value = await settledQuery(harness.container, ordersProvider(1));
    expect(value.error, isA<AppFailure>());
    expect(AppFailure.safe(value.error!).kind, FailureKind.invalidResponse);
  });

  test('orders replies pending at logout cannot appear in the next account',
      () async {
    final oldReply = Completer<OfflineResponse>();
    final harness = CustomerHarness((request) async =>
        request.cookie.contains(userAId)
            ? await oldReply.future
            : OfflineResponse(
                pageJson([orderJson(id: orderBId, number: 'ORD-B')])));
    addTearDown(harness.dispose);
    await harness.login();
    final keep = harness.container.listen(ordersProvider(1), (_, next) {});
    addTearDown(keep.close);
    final old = await harness.backend.requested('/orders');
    await harness.session.logout();
    expect(old.options.cancelToken!.isCancelled, isTrue);
    await harness.login(accountB: true);
    expect(
        (await settledQuery(harness.container, ordersProvider(1)))
            .requireValue
            .items
            .single
            .orderNumber,
        'ORD-B');
    oldReply.complete(OfflineResponse(pageJson([orderJson()])));
    await harness.container.pump();
    expect(
        harness.container
            .read(ordersProvider(1))
            .requireValue
            .items
            .single
            .orderNumber,
        'ORD-B');
  });

  test('the app role is exactly customer at both provider bootstrap and login',
      () async {
    final backend = OfflineBackend((request) => request.path == '/auth/me'
        ? OfflineResponse(userJson(role: 'warehouse_manager'))
        : request.path == '/auth/login'
            ? OfflineResponse({'user': userJson(role: 'delivery_partner')})
            : const OfflineResponse({}));
    final container = ProviderContainer(overrides: [
      apiConfigProvider.overrideWithValue(fixtureConfig()),
      sessionTransportFactoryProvider.overrideWithValue(backend.transport),
    ]);
    addTearDown(container.dispose);
    final state = await settledSession(container, authProvider);
    expect(state.isAuthenticated, isFalse);
    expect(state.failure!.kind, FailureKind.wrongRole);
    expect(container.read(authProvider.notifier).expectedRole, 'customer');
    await expectLater(
        container
            .read(authProvider.notifier)
            .login('fixture@offline.test', 'fixture-password'),
        throwsA(isA<AppFailure>()
            .having((error) => error.kind, 'kind', FailureKind.wrongRole)));
    expect(backend.count('/auth/refresh'), 0);
  });

  test('routers stay stable while auth changes and containers own disposal',
      () async {
    final harness = CustomerHarness(
        (request) async => OfflineResponse(pageJson(<Object?>[])));
    final router = harness.container.read(routerProvider);
    await harness.login();
    expect(identical(router, harness.container.read(routerProvider)), isTrue);
    await harness.session.logout();
    expect(identical(router, harness.container.read(routerProvider)), isTrue);
    harness.dispose();
  });

  test(
      'valid uppercase UUID links use canonical paths without authorization parameters',
      () async {
    const id = 'aabbccdd-aabb-4abb-8abb-aabbccddeeff';
    final harness = CustomerHarness((request) async =>
        request.path.endsWith('/history')
            ? const OfflineResponse(<Object?>[])
            : OfflineResponse(orderJson(id: id)));
    addTearDown(harness.dispose);
    await harness.login();
    expect(
        (await settledQuery(
                harness.container, orderQuery.provider(id.toUpperCase())))
            .requireValue
            .id,
        id);
    expect(
        (await settledQuery(harness.container,
                orderHistoryQuery.provider(id.toUpperCase())))
            .requireValue,
        isEmpty);
    expect(harness.backend.count('/orders/$id'), 1);
    expect(harness.backend.count('/orders/$id/history'), 1);
  });
}
