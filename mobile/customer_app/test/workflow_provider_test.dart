import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_customer/features/account/account_provider.dart';
import 'package:supplyos_customer/features/catalog/catalog_provider.dart';
import 'package:supplyos_customer/features/catalog/product.dart';
import 'package:supplyos_customer/features/ordering/order_quote.dart';
import 'package:supplyos_customer/features/ordering/ordering_provider.dart';
import 'package:supplyos_customer/features/orders/delivery_tracking.dart';
import 'package:supplyos_customer/features/orders/orders_provider.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import 'support/customer_fixtures.dart';
import 'support/workflow_fixtures.dart';

CustomerOrdering filledCart(CustomerHarness harness) {
  final owner = harness.container.read(customerOrderingProvider.notifier);
  final scope = harness.session.snapshot.key!;
  owner.setLine(Product.fromJson(workflowProduct()), '1.250', scope: scope);
  owner.chooseWarehouse(ActiveWarehouse.fromJson(warehouseJson()),
      scope: scope);
  return owner;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
      'search, category, detail and page reads use the effective scoped catalog',
      () async {
    final fixtures = WorkflowFixtures();
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final page = await settledQuery(
        harness.container,
        catalogQuery.provider(const CatalogFilter(
            page: 2, search: 'rice', categoryId: categoryId)));
    expect(page.requireValue.page, 2);
    final detail = await settledQuery(harness.container,
        productDetailQuery.provider(productAId.toUpperCase()));
    expect(detail.requireValue.product.price.text, '41.80');
    expect(
        (await harness.backend.requested('/catalog')).options.queryParameters,
        {'page': 2, 'page_size': 50, 'q': 'rice', 'category_id': categoryId});
    expect((await harness.backend.requested('/catalog/$productAId')).method,
        'GET');
    expect(harness.backend.count('/products'), 0);
    expect(
        (await settledQuery(harness.container, categoriesQuery.provider(null)))
            .requireValue
            .single
            .id,
        categoryId);
  });

  test(
      'invalid browse IDs and mismatched metadata never publish or take fallback paths',
      () async {
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async => request.path.startsWith('/catalog/')
          ? OfflineResponse(workflowDetail(id: productBId))
          : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    expect(
        (await settledQuery(
                harness.container, productDetailQuery.provider('../orders')))
            .hasError,
        isTrue);
    expect(
        (await settledQuery(
                harness.container, productDetailQuery.provider(productAId)))
            .hasError,
        isTrue);
    expect(
        harness.backend.requests
            .where((request) => request.path.startsWith('/catalog/'))
            .length,
        1);
    expect(
        (await settledQuery(harness.container,
                catalogQuery.provider(const CatalogFilter(page: 0))))
            .hasError,
        isTrue);
    expect(harness.backend.count('/catalog'), 0);
  });

  test(
      'active warehouse read filters inactive rows and refuses an inactive selection',
      () async {
    final harness = CustomerHarness(WorkflowFixtures().handle);
    addTearDown(harness.dispose);
    await harness.login();
    final rows = (await settledQuery(
            harness.container, activeWarehousesQuery.provider(null)))
        .requireValue;
    expect(rows.map((row) => row.id), [warehouseId]);
    final owner = filledCart(harness);
    expect(
        () => owner.chooseWarehouse(
            ActiveWarehouse.fromJson(warehouseJson(active: false)),
            scope: harness.session.snapshot.key!),
        throwsA(isA<AppFailure>()));
    expect(harness.container.read(customerOrderingProvider).warehouse!.id,
        warehouseId);
  });

  test(
      'cart preserves exact product-ID quantities and is retained without route listeners',
      () async {
    final harness = CustomerHarness(WorkflowFixtures().handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final scope = harness.session.snapshot.key!;
    owner.setLine(Product.fromJson(workflowProduct()), '2.500', scope: scope);
    await harness.container.pump();
    expect(
        harness.container.read(customerOrderingProvider).lines.single.quantity,
        '2.500');
    expect(
        identical(
            owner, harness.container.read(customerOrderingProvider.notifier)),
        isTrue);
    owner.removeLine(productAId, scope: scope);
    expect(harness.container.read(customerOrderingProvider).lines, isEmpty);
    expect(harness.backend.count('/order-quotes'), 0);
    expect(harness.backend.count('/orders/checkout'), 0);
  });

  test(
      'server quote and atomic 201 checkout carry no client amounts or authority fields',
      () async {
    final fixtures = WorkflowFixtures();
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    owner.choosePaymentMode('credit', scope: harness.session.snapshot.key!);
    owner.setDelivery(
        address: '  Address A  ',
        date: '2026-11-17',
        notes: '  Keep upright  ',
        scope: harness.session.snapshot.key!);
    final quote = await owner.requestQuote();
    final quoteRequest = await harness.backend.requested('/order-quotes');
    expect(quoteRequest.method, 'POST');
    expect(quoteRequest.options.queryParameters, isEmpty);
    expect(quoteRequest.body, {
      'warehouse_id': warehouseId,
      'payment_mode': 'credit',
      'delivery_address': 'Address A',
      'scheduled_delivery_date': '2026-11-17',
      'notes': 'Keep upright',
      'items': [
        {'product_id': productAId, 'quantity': '1.250'}
      ],
    });
    expect(quote.id, requestKey(quoteRequest));
    expect(
        harness.container.read(customerOrderingProvider).accepted!.customerId,
        customerAId);
    final receipt = await owner.checkout();
    final checkoutRequest = await harness.backend.requested('/orders/checkout');
    expect(checkoutRequest.body,
        {'quote_id': quote.id, 'quote_proof': quote.proof});
    expect(requestKey(checkoutRequest), quote.id);
    expect(checkoutRequest.options.queryParameters, isEmpty);
    expect(receipt.order.status, 'reserved');
    expect(receipt.order.grandTotal.text, quote.grandTotal.text);
    expect(receipt.order.currencyCode, 'USD');
    expect(harness.container.read(customerOrderingProvider).lines, isEmpty);
    expect(
        harness.container.read(customerOrderingProvider).lastReceipt!.order.id,
        receipt.order.id);
    expect((await owner.checkout()).order.id, receipt.order.id);
    expect(harness.backend.count('/orders/checkout'), 1);
    expect(harness.backend.count('/orders'), 0);
    expect(harness.backend.count('/orders/${receipt.order.id}/reserve'), 0);
    expect(harness.backend.count('/payments'), 0);
  });

  test(
      'cart edits invalidate a resolved quote but cannot change server-accepted receipt data',
      () async {
    final harness = CustomerHarness(WorkflowFixtures().handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    await owner.requestQuote();
    owner.setLine(Product.fromJson(workflowProduct()), '2.000',
        scope: harness.session.snapshot.key!);
    expect(harness.container.read(customerOrderingProvider).accepted, isNull);
    await expectLater(owner.checkout(), throwsA(isA<AppFailure>()));
    expect(harness.backend.count('/orders/checkout'), 0);
  });

  for (final blockers in [
    ['insufficient_stock'],
    ['credit_limit_exceeded'],
    ['insufficient_stock', 'credit_limit_exceeded'],
  ]) {
    test('server blockers $blockers prevent atomic checkout', () async {
      final fixtures = WorkflowFixtures()..blockers = blockers;
      final harness = CustomerHarness(fixtures.handle);
      addTearDown(harness.dispose);
      await harness.login();
      final owner = filledCart(harness);
      owner.choosePaymentMode('credit', scope: harness.session.snapshot.key!);
      final quote = await owner.requestQuote();
      expect(quote.blockers, blockers);
      await expectLater(owner.checkout(), throwsA(isA<AppFailure>()));
      expect(harness.backend.count('/orders/checkout'), 0);
    });
  }

  test(
      'expired quote requires an explicit distinct quote key and renewed acceptance',
      () async {
    final fixtures = WorkflowFixtures()..expires = '2020-01-01T00:00:00Z';
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final expired = await owner.requestQuote();
    await expectLater(owner.checkout(), throwsA(isA<AppFailure>()));
    expect(harness.backend.count('/orders/checkout'), 0);
    fixtures.expires = '2027-11-16T13:45:00Z';
    final fresh = await owner.requestQuote();
    expect(fresh.id, isNot(expired.id));
    expect(harness.backend.count('/orders/checkout'), 0);
    await owner.checkout();
    expect(requestKey(await harness.backend.requested('/orders/checkout')),
        fresh.id);
  });

  test(
      'initial 409 is resolved rejection; a new quote is explicit and never auto-checks out',
      () async {
    var reject = true;
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async =>
          request.path == '/orders/checkout' && reject
              ? const OfflineResponse({'detail': 'unsafe rejection detail'},
                  status: 409)
              : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final original = await owner.requestQuote();
    await expectLater(
        owner.checkout(),
        throwsA(isA<AppFailure>().having(
            (error) => error.isOutcomeUncertain, 'uncertain', isFalse)));
    expect(harness.container.read(customerOrderingProvider).checkout.phase,
        MutationPhase.rejected);
    await expectLater(owner.checkout(), throwsA(isA<AppFailure>()));
    expect(harness.backend.count('/orders/checkout'), 1);
    reject = false;
    final next = await owner.requestQuote();
    expect(next.id, isNot(original.id));
    expect(harness.backend.count('/orders/checkout'), 1);
    await owner.checkout();
    expect(harness.backend.count('/orders/checkout'), 2);
  });

  test(
      'unknown checkout freezes the original request through navigation, edits and a later 409',
      () async {
    var attempts = 0;
    final fixtures = WorkflowFixtures();
    fixtures.intercept = (request) async {
      if (request.path != '/orders/checkout') return null;
      attempts++;
      final key = requestKey(request);
      if (attempts == 1) {
        fixtures.receipts[key] =
            checkoutJson(fixtures.quotes[key]!, fixtures.quoteBodies[key]!);
        return const OfflineResponse({'detail': 'untrusted failure'},
            status: 503);
      }
      if (attempts == 2) return const OfflineResponse({}, status: 409);
      return OfflineResponse(fixtures.receipts[key], status: 201);
    };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final accepted = await owner.requestQuote();
    await expectLater(
        owner.checkout(),
        throwsA(isA<AppFailure>()
            .having((error) => error.isOutcomeUncertain, 'uncertain', isTrue)));
    final original =
        harness.container.read(customerOrderingProvider).checkout.request!;
    await harness.container.pump();
    expect(
        identical(
            owner, harness.container.read(customerOrderingProvider.notifier)),
        isTrue);
    expect(
        () => owner.setLine(Product.fromJson(workflowProduct()), '9.000',
            scope: harness.session.snapshot.key!),
        throwsA(isA<AppFailure>()));
    expect(
        () => owner.choosePaymentMode('credit',
            scope: harness.session.snapshot.key!),
        throwsA(isA<AppFailure>()));
    await expectLater(owner.requestQuote(), throwsA(isA<AppFailure>()));
    await expectLater(owner.checkout(), throwsA(isA<AppFailure>()));
    await expectLater(
        owner.recoverCheckout(),
        throwsA(isA<AppFailure>().having(
            (error) => error.isOutcomeUncertain, 'still unknown', isTrue)));
    expect(harness.container.read(customerOrderingProvider).checkout.phase,
        MutationPhase.uncertain);
    expect(
        identical(
            harness.container.read(customerOrderingProvider).checkout.request,
            original),
        isTrue);
    // Later product prices/lifecycle reads are irrelevant to original 201 recovery.
    fixtures.expires = '2020-01-01T00:00:00Z';
    final recovered = await owner.recoverCheckout();
    expect(recovered.order.status, 'reserved');
    expect(recovered.order.items.single.unitPrice.text, '41.80');
    expect(recovered.quoteId, accepted.id);
    final requests = harness.backend.requests
        .where((request) => request.path == '/orders/checkout')
        .toList();
    expect(requests.length, 3);
    expect(requests.map(requestKey).toSet(), {accepted.id});
    expect(requests.map((request) => request.encodedBody).toSet(),
        {original.encodedBody});
    expect(harness.backend.count('/order-quotes'), 1);
    expect(harness.backend.count('/orders'), 0);
  });

  test(
      'unknown quote replays the original expired quote; only explicit refresh gets a new key',
      () async {
    var lost = true;
    final fixtures = WorkflowFixtures();
    fixtures.intercept = (request) async {
      if (request.path != '/order-quotes' || !lost) return null;
      lost = false;
      final key = requestKey(request);
      final body =
          Map<String, Object?>.from(request.body! as Map<String, Object?>);
      fixtures.quoteBodies[key] = body;
      fixtures.quotes[key] =
          quoteJson(id: key, body: body, expires: '2020-01-01T00:00:00Z');
      return const OfflineResponse({}, status: 503);
    };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    await expectLater(owner.requestQuote(), throwsA(isA<AppFailure>()));
    final frozen =
        harness.container.read(customerOrderingProvider).quote.request!;
    await expectLater(owner.requestQuote(), throwsA(isA<AppFailure>()));
    final recovered = await owner.recoverQuote();
    expect(recovered.expiredAt(DateTime.now()), isTrue);
    expect(recovered.id, frozen.idempotencyKey);
    final refreshed = await owner.requestQuote();
    expect(refreshed.id, isNot(recovered.id));
    final requests = harness.backend.requests
        .where((request) => request.path == '/order-quotes')
        .toList();
    expect(requests[0].encodedBody, requests[1].encodedBody);
    expect(requestKey(requests[0]), requestKey(requests[1]));
    expect(requestKey(requests[2]), isNot(requestKey(requests[0])));
  });

  for (final status in [200, 201]) {
    test(
        'unexpected status or mismatched successful receipt $status remains unknown and locked',
        () async {
      final fixtures = WorkflowFixtures();
      fixtures.intercept = (request) async {
        if (request.path != '/orders/checkout') return null;
        final key = requestKey(request);
        final data =
            checkoutJson(fixtures.quotes[key]!, fixtures.quoteBodies[key]!);
        if (status == 201) data['customer_id'] = customerBId;
        return OfflineResponse(data, status: status);
      };
      final harness = CustomerHarness(fixtures.handle);
      addTearDown(harness.dispose);
      await harness.login();
      final owner = filledCart(harness);
      await owner.requestQuote();
      await expectLater(
          owner.checkout(),
          throwsA(isA<AppFailure>().having(
              (error) => error.isOutcomeUncertain, 'uncertain', isTrue)));
      expect(
          harness.container.read(customerOrderingProvider).lastReceipt, isNull);
      expect(harness.container.read(customerOrderingProvider).isLocked, isTrue);
      expect(harness.backend.count('/orders/checkout'), 1);
    });
  }

  test(
      'double acceptance during an in-flight checkout sends only one original request',
      () async {
    final response = Completer<OfflineResponse>();
    final fixtures = WorkflowFixtures()
      ..intercept = (request) =>
          request.path == '/orders/checkout' ? response.future : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final quote = await owner.requestQuote();
    final first = owner.checkout();
    await harness.backend.requested('/orders/checkout');
    await expectLater(owner.checkout(), throwsA(isA<AppFailure>()));
    response.complete(OfflineResponse(
        checkoutJson(
            fixtures.quotes[quote.id]!, fixtures.quoteBodies[quote.id]!),
        status: 201));
    await first;
    expect(harness.backend.count('/orders/checkout'), 1);
  });

  test(
      'logout clears cart and pending receipt immediately; another account cannot publish or replay it',
      () async {
    final reply = Completer<OfflineResponse>();
    final fixtures = WorkflowFixtures()
      ..intercept =
          (request) => request.path == '/orders/checkout' ? reply.future : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final oldScope = harness.session.snapshot.key!;
    final quote = await owner.requestQuote();
    final checkout = owner.checkout();
    final denied = expectLater(checkout, throwsA(isA<AppFailure>()));
    await harness.backend.requested('/orders/checkout');
    final logout = harness.session.logout();
    expect(harness.container.read(customerOrderingProvider).lines, isEmpty);
    expect(harness.container.read(customerOrderingProvider).accepted, isNull);
    expect(
        harness.container.read(customerOrderingProvider).lastReceipt, isNull);
    await logout;
    await harness.login(accountB: true);
    reply.complete(OfflineResponse(
        checkoutJson(
            fixtures.quotes[quote.id]!, fixtures.quoteBodies[quote.id]!),
        status: 201));
    await denied;
    expect(
        harness.container.read(customerOrderingProvider).lastReceipt, isNull);
    expect(
        () => owner.setLine(Product.fromJson(workflowProduct()), '1',
            scope: oldScope),
        throwsA(isA<AppFailure>()));
    await expectLater(owner.recoverCheckout(), throwsA(isA<AppFailure>()));
    expect(harness.backend.count('/orders/checkout'), 1);
  });

  test(
      'own account, ledger and payments paths are derived from the linked profile and fail closed',
      () async {
    final fixtures = WorkflowFixtures();
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    expect(
        (await settledQuery(
                harness.container, customerProfileQuery.provider(null)))
            .requireValue
            .id,
        customerAId);
    expect(
        (await settledQuery(harness.container, ledgerQuery.provider(null)))
            .requireValue
            .entries
            .single
            .note,
        'Ledger A');
    expect(
        (await settledQuery(
                harness.container, paymentsQuery.provider(orderAId)))
            .requireValue
            .receipts
            .single
            .customerId,
        customerAId);
    expect(
        (await harness.backend.requested('/payments')).options.queryParameters,
        {'customer_id': customerAId, 'order_id': orderAId});
    expect(
        (await harness.backend.requested('/customers/$customerAId/ledger'))
            .options
            .queryParameters,
        {'limit': 100});
    await harness.session.logout();
    await harness.login(accountB: true);
    expect(
        (await settledQuery(harness.container, ledgerQuery.provider(null)))
            .requireValue
            .entries
            .single
            .note,
        'Ledger B');
    expect(
        (await settledQuery(harness.container, paymentsQuery.provider(null)))
            .requireValue
            .receipts
            .single
            .customerId,
        customerBId);
    expect(harness.backend.count('/customers/$customerBId/ledger'), 1);
    for (final request in harness.backend.requests
        .where((request) => !request.path.startsWith('/auth/'))) {
      expect(request.method, 'GET');
      expect(request.body, isNull);
    }
  });

  test(
      'payments reject foreign customer/order receipts instead of displaying them',
      () async {
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async => request.path == '/payments'
          ? OfflineResponse([paymentJson(accountB: true)])
          : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final keep = harness.container
        .listen(paymentsQuery.provider(orderAId), (_, next) {});
    addTearDown(keep.close);
    expect(
        (await settledQuery(
                harness.container, paymentsQuery.provider(orderAId)))
            .hasError,
        isTrue);
    fixtures.intercept = (request) async => request.path == '/payments'
        ? OfflineResponse([paymentJson(order: orderBId)])
        : null;
    await harness.container.read(paymentsQuery.refreshProvider(orderAId))();
    expect(harness.container.read(paymentsQuery.provider(orderAId)).hasError,
        isTrue);
  });

  test(
      'own tracking filters only actual returned matching order IDs, with no operator API',
      () async {
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async => request.path == '/deliveries'
          ? OfflineResponse([
              deliveryJson(),
              {...deliveryJson(order: orderBId), 'id': productBId}
            ])
          : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final rows = (await settledQuery(
            harness.container, deliveryTrackingQuery.provider(orderAId)))
        .requireValue;
    expect(rows.length, 1);
    expect(rows.single.orderId, orderAId);
    expect(harness.backend.requests.last.method, 'GET');
    expect(harness.backend.requests.last.options.queryParameters, isEmpty);
  });

  test(
      'order filters reset page and carry only the actual status/search contract',
      () async {
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async => request.path == '/orders'
          ? OfflineResponse(pageJson([
              {...orderJson(), 'status': 'reserved'}
            ], page: 2))
          : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final result = await settledQuery(
        harness.container,
        filteredOrdersQuery.provider(
            (const OrderFilter(search: 'ORD', status: 'reserved'), 2)));
    expect(result.requireValue.page, 2);
    expect((await harness.backend.requested('/orders')).options.queryParameters,
        {'page': 2, 'page_size': 50, 'q': 'ORD', 'status': 'reserved'});
  });
}
