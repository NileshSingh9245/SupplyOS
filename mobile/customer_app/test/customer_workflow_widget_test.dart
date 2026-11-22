import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_customer/features/ordering/ordering_provider.dart';
import 'package:supplyos_customer/main.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import '../../packages/supplyos_core/test/support/widget_harness.dart';
import 'support/customer_fixtures.dart';
import 'support/workflow_fixtures.dart';
import 'workflow_provider_test.dart' show filledCart;

Future<void> showCustomerApp(
    WidgetTester tester, CustomerHarness harness) async {
  addTearDown(() async {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });
  await tester.pumpWidget(UncontrolledProviderScope(
      container: harness.container, child: const SupplyOSCustomerApp()));
  await tester.pumpAndSettle();
}

Future<void> openRoute(
    WidgetTester tester, CustomerHarness harness, String route) async {
  harness.container.read(routerProvider).go(route);
  await tester.pumpAndSettle();
}

Future<void> reveal(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) {
    final scrollable = find
        .byWidgetPredicate((widget) =>
            widget is Scrollable && widget.axisDirection == AxisDirection.down)
        .first;
    final position = tester.state<ScrollableState>(scrollable).position;
    position.jumpTo(position.minScrollExtent);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(finder, 250,
        scrollable: scrollable, maxScrolls: 60);
  }
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

Future<void> tapVisible(WidgetTester tester, Finder finder) async {
  await reveal(tester, finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'a customer completes product browsing, exact cart, choices, quote, checkout and own records',
      (tester) async {
    final fixtures = WorkflowFixtures();
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showCustomerApp(tester, harness);
    await tapVisible(tester, find.text('View product'));
    expect(find.text('Product details'), findsOneWidget);
    expect(find.textContaining('999.00'), findsNothing);
    final quantity = find.byKey(const ValueKey('product-quantity'));
    await reveal(tester, quantity);
    await tester.enterText(quantity, '1.250');
    await tapVisible(tester, find.text('Add to cart'));
    expect(find.text('Your cart'), findsOneWidget);
    expect(
        harness.container.read(customerOrderingProvider).lines.single.quantity,
        '1.250');
    final warehouse = find.byType(DropdownButtonFormField<String>);
    await reveal(tester, warehouse);
    await tester.tap(warehouse);
    await tester.pumpAndSettle();
    expect(find.text('Retired warehouse'), findsNothing);
    await tester.tap(find.text('Central warehouse').last);
    await tester.pumpAndSettle();
    await tapVisible(tester, find.text('Credit'));
    await tapVisible(tester, find.text('Use account address'));
    expect(
        tester
            .widget<TextFormField>(
                find.byKey(const ValueKey('delivery-address')))
            .controller!
            .text,
        'Address A');
    await tapVisible(tester, find.text('Get server quote'));
    expect(find.text('Review & checkout'), findsOneWidget);
    expect(find.text('Your server quote'), findsOneWidget);
    await reveal(tester, find.text('USD 54.86').first);
    expect(find.text('USD 54.86'), findsWidgets);
    await tapVisible(tester, find.text('Accept quote & place order'));
    expect(find.text('Order confirmed'), findsOneWidget);
    expect(harness.backend.count('/orders/checkout'), 1);
    expect(harness.backend.count('/order-quotes'), 1);
    final quote = harness.backend.requests
        .singleWhere((request) => request.path == '/order-quotes');
    final checkout = harness.backend.requests
        .singleWhere((request) => request.path == '/orders/checkout');
    expect(requestKey(checkout), requestKey(quote));
    expect(
        JsonObject(quote.body)
            .list('items', JsonObject.new)
            .single
            .string('quantity'),
        '1.250');
    await tapVisible(tester, find.text('View order'));
    expect(find.text('Order details'), findsOneWidget);
    await tapVisible(tester, find.text('Track delivery'));
    expect(find.text('Delivery tracking'), findsOneWidget);
    expect(find.text('Verify OTP'), findsNothing);
    expect(find.text('Upload proof'), findsNothing);
    await tester.tap(find.byTooltip('Back to order'));
    await tester.pumpAndSettle();
    await tapVisible(tester, find.text('Recorded payments'));
    expect(harness.backend.requests.last.path, '/payments');
    expect(harness.backend.requests.last.options.queryParameters,
        {'customer_id': customerAId, 'order_id': orderAId});
    expect(find.text('Collect payment'), findsNothing);
    expect(find.text('Pay now'), findsNothing);
    await tester.tap(find.text('Account'));
    await tester.pumpAndSettle();
    expect(find.text('Account A'), findsOneWidget);
    await tapVisible(tester, find.text('View ledger'));
    expect(find.text('Account ledger'), findsOneWidget);
    await reveal(tester, find.text('Ledger A'));
    expect(find.text('Ledger A'), findsOneWidget);
    expect(find.text('Download invoice'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'search/category selection and pagination keep their original filter on product return',
      (tester) async {
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async {
        if (request.path != '/catalog') return null;
        final page = request.options.queryParameters['page'] as int;
        return OfflineResponse(pageJson(
            [workflowProduct(name: 'Rice page $page')],
            page: page, total: 51));
      };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showCustomerApp(tester, harness);
    await tester.enterText(find.byType(TextField), 'rice');
    await tester.tap(find.byTooltip('Search'));
    await tester.pumpAndSettle();
    await tapVisible(tester, find.text('Essentials'));
    await tapVisible(tester, find.byTooltip('Next page'));
    expect(find.text('Rice page 2'), findsOneWidget);
    await reveal(tester, find.text('Page 2 | 51 total'));
    expect(find.text('Page 2 | 51 total'), findsOneWidget);
    final request = harness.backend.requests
        .lastWhere((request) => request.path == '/catalog');
    expect(request.options.queryParameters,
        {'page': 2, 'page_size': 50, 'q': 'rice', 'category_id': categoryId});
    await tapVisible(tester, find.text('View product'));
    await tester.tap(find.byTooltip('Back to catalog'));
    await tester.pumpAndSettle();
    expect(find.text('Rice page 2'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        'rice');
    await tapVisible(tester, find.byTooltip('Previous page'));
    expect(find.text('Rice page 1'), findsOneWidget);
    final count = harness.backend.count('/catalog');
    await tester.tap(find.byTooltip('Refresh catalog'));
    await tester.pumpAndSettle();
    expect(harness.backend.count('/catalog'), count + 1);
  });

  testWidgets(
      'a pending next catalog page hides old rows and has a safe error/retry path',
      (tester) async {
    final next = Completer<OfflineResponse>();
    var available = false;
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async {
        if (request.path != '/catalog') return null;
        final page = request.options.queryParameters['page'] as int;
        if (page == 2 && !available) return next.future;
        return OfflineResponse(pageJson(
            [workflowProduct(name: 'Rice page $page')],
            page: page, total: 51));
      };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showCustomerApp(tester, harness);
    await reveal(tester, find.byTooltip('Next page'));
    await tester.tap(find.byTooltip('Next page'));
    await pumpUntil(tester, () => harness.backend.count('/catalog') == 2);
    expect(find.text('Rice page 1'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    next.complete(const OfflineResponse({'detail': 'unsafe upstream detail'},
        status: 503));
    await tester.pumpAndSettle();
    expect(find.text('Unable to load catalog.'), findsOneWidget);
    expect(find.textContaining('unsafe upstream'), findsNothing);
    available = true;
    await tapVisible(tester, find.text('Retry'));
    expect(find.text('Rice page 2'), findsOneWidget);
  });

  testWidgets(
      'cart invalid quantity drafts and invalid dates never reach quote HTTP',
      (tester) async {
    final harness = CustomerHarness(WorkflowFixtures().handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    filledCart(harness);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart');
    final quantity = find.byKey(const ValueKey('cart-quantity-$productAId'));
    await reveal(tester, quantity);
    await tester.enterText(quantity, '0.000');
    await tapVisible(tester, find.text('Get server quote'));
    expect(harness.backend.count('/order-quotes'), 0);
    await reveal(tester, quantity);
    await tester.enterText(quantity, '1.250');
    final date = find.byKey(const ValueKey('delivery-date'));
    await reveal(tester, date);
    await tester.enterText(date, '2026-02-30');
    await tapVisible(tester, find.text('Get server quote'));
    expect(harness.backend.count('/order-quotes'), 0);
    expect(find.text('Enter a valid date as YYYY-MM-DD.'), findsOneWidget);
  });

  testWidgets(
      'cart requires an explicit active warehouse, never auto-selecting the first row',
      (tester) async {
    final fixtures = WorkflowFixtures();
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final owner = filledCart(harness);
    owner.chooseWarehouse(null, scope: harness.session.snapshot.key!);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart');
    await reveal(tester, find.text('Get server quote'));
    final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Get server quote'));
    expect(button.onPressed, isNull);
    expect(harness.container.read(customerOrderingProvider).warehouse, isNull);
    expect(harness.backend.count('/order-quotes'), 0);
  });

  testWidgets(
      'server stock/credit blockers remain visible and cannot be accepted',
      (tester) async {
    final fixtures = WorkflowFixtures()
      ..blockers = ['insufficient_stock', 'credit_limit_exceeded'];
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final owner = filledCart(harness);
    owner.choosePaymentMode('credit', scope: harness.session.snapshot.key!);
    await tester.runAsync(owner.requestQuote);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart/quote');
    await reveal(tester, find.text('Accept quote & place order'));
    expect(find.text('Server blocker: insufficient stock for this cart.'),
        findsOneWidget);
    expect(
        find.text(
            'Server blocker: the credit limit does not cover this order.'),
        findsOneWidget);
    expect(
        tester
            .widget<FilledButton>(
                find.widgetWithText(FilledButton, 'Accept quote & place order'))
            .onPressed,
        isNull);
    expect(harness.backend.count('/orders/checkout'), 0);
  });

  testWidgets(
      'expiry shows a distinct new-quote action without any automatic replacement checkout',
      (tester) async {
    final fixtures = WorkflowFixtures()..expires = '2020-01-01T00:00:00Z';
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final owner = filledCart(harness);
    final quote = await tester.runAsync(owner.requestQuote);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart/quote');
    expect(find.textContaining('This quote has expired.'), findsOneWidget);
    await reveal(tester, find.text('Accept quote & place order'));
    expect(
        tester
            .widget<FilledButton>(
                find.widgetWithText(FilledButton, 'Accept quote & place order'))
            .onPressed,
        isNull);
    fixtures.expires = '2027-11-16T13:45:00Z';
    await tapVisible(tester, find.text('Request new quote'));
    expect(harness.container.read(customerOrderingProvider).accepted!.quote.id,
        isNot(quote!.id));
    expect(harness.backend.count('/order-quotes'), 2);
    expect(harness.backend.count('/orders/checkout'), 0);
  });

  testWidgets(
      'an initial checkout conflict has safe copy and needs a new explicit acceptance',
      (tester) async {
    var reject = true;
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async => request.path == '/orders/checkout' &&
              reject
          ? const OfflineResponse({'detail': 'sensitive conflict'}, status: 409)
          : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final owner = filledCart(harness);
    await tester.runAsync(owner.requestQuote);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart/quote');
    await tapVisible(tester, find.text('Accept quote & place order'));
    expect(harness.container.read(customerOrderingProvider).checkout.phase,
        MutationPhase.rejected);
    expect(find.textContaining('sensitive conflict'), findsNothing);
    reject = false;
    await tapVisible(tester, find.text('Request new quote'));
    expect(harness.backend.count('/orders/checkout'), 1);
    await tapVisible(tester, find.text('Accept quote & place order'));
    expect(find.text('Order confirmed'), findsOneWidget);
    expect(harness.backend.count('/orders/checkout'), 2);
  });

  testWidgets(
      'unknown checkout survives leaving/re-entering the route and recovers ONLY its original bytes',
      (tester) async {
    var lost = true;
    final fixtures = WorkflowFixtures();
    fixtures.intercept = (request) async {
      if (request.path != '/orders/checkout' || !lost) return null;
      lost = false;
      final key = requestKey(request);
      fixtures.receipts[key] =
          checkoutJson(fixtures.quotes[key]!, fixtures.quoteBodies[key]!);
      return const OfflineResponse({}, status: 503);
    };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final owner = filledCart(harness);
    await tester.runAsync(owner.requestQuote);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart/quote');
    await tapVisible(tester, find.text('Accept quote & place order'));
    expect(harness.container.read(customerOrderingProvider).checkout.phase,
        MutationPhase.uncertain);
    await tester.tap(find.text('Orders'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cart'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Checkout outcome unknown.'), findsOneWidget);
    await reveal(tester, find.text('Recover original checkout'));
    await tester.tap(find.text('Recover original checkout'));
    await tester.pumpAndSettle();
    expect(find.text('Order confirmed'), findsOneWidget);
    final requests = harness.backend.requests
        .where((request) => request.path == '/orders/checkout')
        .toList();
    expect(requests.length, 2);
    expect(requestKey(requests.first), requestKey(requests.last));
    expect(requests.first.encodedBody, requests.last.encodedBody);
    expect(harness.backend.count('/order-quotes'), 1);
  });

  testWidgets(
      'unknown quote recovery retains quantities and cannot issue a new key from an edit',
      (tester) async {
    var lost = true;
    final fixtures = WorkflowFixtures();
    fixtures.intercept = (request) async {
      if (request.path != '/order-quotes' || !lost) return null;
      lost = false;
      final key = requestKey(request);
      final body = request.body! as Map<String, Object?>;
      fixtures.quoteBodies[key] = body;
      fixtures.quotes[key] = quoteJson(id: key, body: body);
      return const OfflineResponse({}, status: 503);
    };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    filledCart(harness);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart');
    await tapVisible(tester, find.text('Get server quote'));
    expect(find.textContaining('Quote response unknown.'), findsOneWidget);
    await tapVisible(tester, find.text('Recover original quote'));
    expect(
        harness.container
            .read(customerOrderingProvider)
            .accepted!
            .quote
            .items
            .single
            .quantity
            .text,
        '1.250');
    final requests = harness.backend.requests
        .where((request) => request.path == '/order-quotes')
        .toList();
    expect(requestKey(requests.first), requestKey(requests.last));
    expect(requests.first.encodedBody, requests.last.encodedBody);
    expect(harness.backend.count('/orders/checkout'), 0);
  });

  testWidgets(
      'a checkout in flight disables new intent and preserves the confirmed receipt across navigation',
      (tester) async {
    final reply = Completer<OfflineResponse>();
    final fixtures = WorkflowFixtures()
      ..intercept =
          (request) => request.path == '/orders/checkout' ? reply.future : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final owner = filledCart(harness);
    final quote = await tester.runAsync(owner.requestQuote);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart/quote');
    await reveal(tester, find.text('Accept quote & place order'));
    await tester.tap(find.text('Accept quote & place order'));
    await pumpUntil(
        tester, () => harness.backend.count('/orders/checkout') == 1);
    expect(harness.container.read(customerOrderingProvider).checkout.phase,
        MutationPhase.sending);
    await tester.tap(find.text('Catalog'));
    await pumpUntil(
        tester, () => find.text('Your next supply run').evaluate().isNotEmpty);
    await tester.runAsync(() async {
      reply.complete(OfflineResponse(
          checkoutJson(
              fixtures.quotes[quote!.id]!, fixtures.quoteBodies[quote.id]!),
          status: 201));
    });
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cart'));
    await tester.pumpAndSettle();
    expect(find.text('Order confirmed'), findsOneWidget);
    expect(find.text('View confirmed order'), findsOneWidget);
    expect(harness.backend.count('/orders/checkout'), 1);
  });

  testWidgets(
      'logout from an unresolved checkout clears private views before account B signs in',
      (tester) async {
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async => request.path == '/orders/checkout'
          ? const OfflineResponse({}, status: 503)
          : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final owner = filledCart(harness);
    await tester.runAsync(owner.requestQuote);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart/quote');
    await tapVisible(tester, find.text('Accept quote & place order'));
    await tester.tap(find.byTooltip('Sign out'));
    await tester.pumpAndSettle();
    expect(find.text('Sign in'), findsOneWidget);
    expect(find.text('Warehouse rice'), findsNothing);
    await tester.runAsync(() => harness.login(accountB: true));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cart'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Your cart is empty.'), findsOneWidget);
    expect(find.textContaining('Checkout outcome unknown.'), findsNothing);
    expect(harness.container.read(customerOrderingProvider).accepted, isNull);
    await tester.tap(find.text('Account'));
    await tester.pumpAndSettle();
    expect(find.text('Account B'), findsOneWidget);
    expect(find.text('Account A'), findsNothing);
  });

  testWidgets(
      'own account balances, ledger and receipts disclose unknown currency and no writing controls',
      (tester) async {
    final harness = CustomerHarness(WorkflowFixtures().handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/account');
    await reveal(tester, find.text('37.25 (currency not recorded)'));
    expect(find.text('37.25 (currency not recorded)'), findsOneWidget);
    expect(find.textContaining('INR'), findsNothing);
    await tapVisible(tester, find.text('Recorded payments'));
    expect(find.text('37.2500 (currency not recorded)'), findsOneWidget);
    expect(find.text('Record payment'), findsNothing);
    expect(find.text('Download PDF'), findsNothing);
    await openRoute(tester, harness, '/account/ledger');
    await reveal(tester, find.text('-7.0100 (currency not recorded)'));
    expect(find.text('-7.0100 (currency not recorded)'), findsOneWidget);
  });

  for (final viewport in [
    (const Size(320, 480), 2.0),
    (const Size(360, 800), 1.6),
    (const Size(844, 320), 2.0),
    (const Size(1024, 768), 1.4),
  ]) {
    testWidgets(
        'implemented phone/tablet routes handle ${viewport.$1.width}px and text scale ${viewport.$2}',
        (tester) async {
      await tester.binding.setSurfaceSize(viewport.$1);
      tester.platformDispatcher.textScaleFactorTestValue = viewport.$2;
      addTearDown(() {
        tester.platformDispatcher.clearTextScaleFactorTestValue();
        return tester.binding.setSurfaceSize(null);
      });
      final harness = CustomerHarness(WorkflowFixtures().handle);
      addTearDown(harness.dispose);
      await tester.runAsync(() => harness.login());
      final owner = filledCart(harness);
      await tester.runAsync(owner.requestQuote);
      await showCustomerApp(tester, harness);
      for (final route in [
        '/catalog/$productAId',
        '/cart',
        '/cart/quote',
        '/orders',
        '/orders/$orderAId',
        '/orders/$orderAId/tracking',
        '/account',
        '/account/ledger',
        '/account/payments'
      ]) {
        await openRoute(tester, harness, route);
        expect(tester.takeException(), isNull, reason: route);
      }
      if (viewport.$1.width >= 840) {
        expect(find.byType(NavigationRail), findsOneWidget);
      } else {
        expect(find.byType(NavigationBar), findsOneWidget);
      }
    });
  }

  testWidgets(
      'customer navigation and primary actions have labeled accessible tap targets',
      (tester) async {
    final harness = CustomerHarness(WorkflowFixtures().handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final semantics = tester.ensureSemantics();
    try {
      await showCustomerApp(tester, harness);
      expect(tester, meetsGuideline(labeledTapTargetGuideline));
      expect(tester, meetsGuideline(androidTapTargetGuideline));
      expect(tester, meetsGuideline(textContrastGuideline));
    } finally {
      semantics.dispose();
    }
  });

  testWidgets(
      'own order status/search controls preserve filters and reset their server page',
      (tester) async {
    final fixtures = WorkflowFixtures()
      ..intercept = (request) async {
        if (request.path != '/orders') return null;
        final page = request.options.queryParameters['page'] as int;
        return OfflineResponse(pageJson([
          {
            ...orderJson(),
            'status': request.options.queryParameters['status'] ?? 'reserved',
          }
        ], page: page, total: 51));
      };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showCustomerApp(tester, harness);
    await tester.tap(find.text('Orders'));
    await tester.pumpAndSettle();
    await tapVisible(tester, find.widgetWithText(ChoiceChip, 'Reserved'));
    await reveal(tester, find.byType(TextField));
    await tester.enterText(find.byType(TextField), 'ORD-');
    await tester.tap(find.byTooltip('Search'));
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byTooltip('Next page'));
    expect(harness.backend.requests.last.options.queryParameters,
        {'page': 2, 'page_size': 50, 'status': 'reserved', 'q': 'ORD-'});
    await tapVisible(tester, find.widgetWithText(ChoiceChip, 'Completed'));
    expect(harness.backend.requests.last.options.queryParameters,
        {'page': 1, 'page_size': 50, 'status': 'completed', 'q': 'ORD-'});
  });

  testWidgets(
      'own account loading and sanitized errors retry real reads without fallback data',
      (tester) async {
    final reply = Completer<OfflineResponse>();
    var profiles = 0;
    final fixtures = WorkflowFixtures()
      ..intercept = (request) {
        if (request.path == '/customers' && ++profiles == 1) {
          return reply.future;
        }
        return null;
      };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showCustomerApp(tester, harness);
    harness.container.read(routerProvider).go('/account');
    await pumpUntil(tester, () => harness.backend.count('/customers') == 1);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('Account A'), findsNothing);
    reply.complete(const OfflineResponse(
        {'detail': 'private upstream account data'},
        status: 503));
    await tester.pumpAndSettle();
    expect(find.text('Unable to load your account.'), findsOneWidget);
    expect(find.textContaining('private upstream'), findsNothing);
    await tapVisible(tester, find.text('Retry'));
    expect(harness.backend.count('/customers'), 2);
    expect(find.text('Account A'), findsOneWidget);
  });

  testWidgets(
      'held renewal locks cart and later quotes the visible exact draft rather than an older quantity',
      (tester) async {
    final me = Completer<OfflineResponse>();
    var reads = 0;
    final fixtures = WorkflowFixtures()
      ..intercept = (request) {
        if (request.path == '/renewal-probe') {
          return OfflineResponse({}, status: ++reads == 1 ? 401 : 200);
        }
        if (request.path == '/auth/me') return me.future;
        return null;
      };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    filledCart(harness);
    await showCustomerApp(tester, harness);
    await openRoute(tester, harness, '/cart');
    final quantity = find.byKey(const ValueKey('cart-quantity-$productAId'));
    await reveal(tester, quantity);
    late Future<Object?> renewal;
    await tester.runAsync(() async {
      renewal = harness.session
          .get('/renewal-probe', scope: harness.session.snapshot.key!);
      await harness.backend.requested('/auth/me');
    });
    await tester.enterText(quantity, '2.500');
    await tester.pump();
    expect(tester.widget<TextFormField>(quantity).enabled, isFalse);
    expect(
        harness.container.read(customerOrderingProvider).lines.single.quantity,
        '1.250');
    await tester.runAsync(() async {
      me.complete(OfflineResponse(userJson()));
      await renewal;
    });
    await tester.pumpAndSettle();
    await tapVisible(tester, find.text('Get server quote'));
    final request = harness.backend.requests
        .singleWhere((request) => request.path == '/order-quotes');
    expect(
        JsonObject(request.body)
            .list('items', JsonObject.new)
            .single
            .string('quantity'),
        '2.500');
  });
}
