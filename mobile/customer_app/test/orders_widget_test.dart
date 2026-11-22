import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_customer/features/auth/auth_provider.dart';
import 'package:supplyos_customer/features/catalog/catalog_screen.dart';
import 'package:supplyos_customer/features/orders/order_detail_screen.dart';
import 'package:supplyos_customer/features/orders/orders_screen.dart';
import 'package:supplyos_customer/main.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import '../../packages/supplyos_core/test/support/widget_harness.dart';
import 'support/customer_fixtures.dart';

Future<void> showScreen(
    WidgetTester tester, CustomerHarness harness, Widget screen) async {
  await tester.pumpWidget(UncontrolledProviderScope(
    container: harness.container,
    child: MaterialApp(home: screen),
  ));
}

void main() {
  testWidgets(
      'orders loading transitions to empty with refresh and disabled next page',
      (tester) async {
    final reply = Completer<OfflineResponse>();
    final harness = CustomerHarness((request) => reply.future);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showScreen(tester, harness, const OrdersScreen());
    await pumpUntil(tester, () => harness.backend.count('/orders') == 1);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.byTooltip('Sign out'), findsOneWidget);
    reply.complete(OfflineResponse(pageJson(<Object?>[])));
    await tester.pumpAndSettle();
    expect(find.text('No orders on this page.'), findsOneWidget);
    expect(find.byType(RefreshIndicator), findsOneWidget);
    expect(
        tester
            .widget<IconButton>(
                find.widgetWithIcon(IconButton, Icons.chevron_right))
            .onPressed,
        isNull);
    expect(find.text('Page 1 | 0 total'), findsOneWidget);
  });

  testWidgets(
      'orders error is sanitized and Retry really requests the page again',
      (tester) async {
    var available = false;
    final harness = CustomerHarness((request) async => available
        ? OfflineResponse(pageJson([orderJson()]))
        : const OfflineResponse({'detail': 'untrusted-provider-message'},
            status: 503));
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showScreen(tester, harness, const OrdersScreen());
    await tester.pumpAndSettle();
    expect(find.text('Unable to load orders.'), findsOneWidget);
    expect(find.textContaining('untrusted-provider'), findsNothing);
    available = true;
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('ORD-A'), findsOneWidget);
    expect(find.text('INR 1234567890123.4567890'), findsOneWidget);
    expect(harness.backend.count('/orders'), 2);
  });

  testWidgets(
      'pagination uses server metadata and supports next, previous and refresh',
      (tester) async {
    final harness = CustomerHarness((request) async {
      final page = request.options.queryParameters['page']! as int;
      return OfflineResponse(pageJson([
        orderJson(
            id: page == 1 ? orderAId : orderBId,
            number: page == 1 ? 'ORD-A' : 'ORD-B'),
      ], page: page, total: 51));
    });
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showScreen(tester, harness, const OrdersScreen());
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Next page'));
    await tester.pumpAndSettle();
    expect(find.text('ORD-B'), findsOneWidget);
    expect(find.text('ORD-A'), findsNothing);
    expect(find.text('Page 2 | 51 total'), findsOneWidget);
    expect(
        tester
            .widget<IconButton>(
                find.widgetWithIcon(IconButton, Icons.chevron_right))
            .onPressed,
        isNull);
    await tester.tap(find.byTooltip('Previous page'));
    await tester.pumpAndSettle();
    expect(find.text('ORD-A'), findsOneWidget);
    final before = harness.backend.count('/orders');
    await tester.tap(find.byTooltip('Refresh orders'));
    await tester.pumpAndSettle();
    expect(harness.backend.count('/orders'), before + 1);
    for (final request in harness.backend.requests
        .where((request) => request.path == '/orders')) {
      expect(request.options.queryParameters['page_size'], 50);
    }
  });

  testWidgets(
      'a failing next page has explicit error and retry rather than stale previous rows',
      (tester) async {
    var nextAvailable = false;
    final harness = CustomerHarness((request) async {
      final page = request.options.queryParameters['page']! as int;
      if (page == 2 && !nextAvailable) {
        return const OfflineResponse({}, status: 503);
      }
      return OfflineResponse(pageJson(
          [orderJson(number: page == 1 ? 'ORD-A' : 'ORD-B')],
          page: page, total: 51));
    });
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showScreen(tester, harness, const OrdersScreen());
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Next page'));
    await tester.pumpAndSettle();
    expect(find.text('ORD-A'), findsNothing);
    expect(find.text('Unable to load orders.'), findsOneWidget);
    nextAvailable = true;
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('ORD-B'), findsOneWidget);
  });

  testWidgets(
      'order detail displays server money and chronological history without operational actions',
      (tester) async {
    final harness =
        CustomerHarness((request) async => request.path.endsWith('/history')
            ? OfflineResponse([
                historyJson(
                    id: orderBId,
                    from: 'pending',
                    to: 'future_hold',
                    at: '2026-11-12T04:00:00Z',
                    note: 'Later event'),
                historyJson(note: 'First event'),
              ])
            : OfflineResponse(orderJson()));
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showScreen(tester, harness, const OrderDetailScreen(id: orderAId));
    await tester.pumpAndSettle();
    expect(find.text('ORD-A'), findsOneWidget);
    await tester.scrollUntilVisible(
        find.text('INR 1234567890123.4567890'), 250);
    expect(find.text('INR 1234567890123.4567890'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('History / oldest first'), 300);
    expect(find.text('First event'), findsOneWidget);
    expect(find.text('Later event'), findsOneWidget);
    final firstY = tester.getTopLeft(find.text('First event')).dy;
    final laterY = tester.getTopLeft(find.text('Later event')).dy;
    expect(firstY, lessThan(laterY));
    expect(find.text('Pending -> Other status: future_hold'), findsOneWidget);
    expect(find.text('Collect payment'), findsNothing);
    expect(find.text('Confirm order'), findsNothing);
    expect(harness.backend.count('/orders/$orderAId'), 1);
    expect(harness.backend.count('/orders/$orderAId/history'), 1);
  });

  testWidgets('history has independent loading, empty and error/retry states',
      (tester) async {
    final history = Completer<OfflineResponse>();
    var failHistory = false;
    final harness = CustomerHarness((request) async {
      if (request.path.endsWith('/history')) {
        return failHistory
            ? const OfflineResponse({}, status: 503)
            : await history.future;
      }
      return OfflineResponse(orderJson());
    });
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showScreen(tester, harness, const OrderDetailScreen(id: orderAId));
    await pumpUntil(
        tester, () => harness.backend.count('/orders/$orderAId/history') == 1);
    await tester.scrollUntilVisible(find.text('History / oldest first'), 300);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    history.complete(const OfflineResponse(<Object?>[]));
    await tester.pumpAndSettle();
    expect(find.text('No history recorded.'), findsOneWidget);
    failHistory = true;
    await tester.tap(find.byTooltip('Refresh order'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('History / oldest first'), 300);
    expect(find.text('Unable to load history.'), findsOneWidget);
    expect(find.text('Retry history'), findsOneWidget);
  });

  testWidgets(
      'catalog states show the server customer price, currency and tax without base fallback',
      (tester) async {
    var phase = 0;
    final harness = CustomerHarness((request) async => switch (phase) {
          0 => const OfflineResponse({}, status: 503),
          1 => OfflineResponse(pageJson(<Object?>[])),
          _ => OfflineResponse(pageJson([productJson()])),
        });
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showScreen(tester, harness, const CatalogScreen());
    await tester.pumpAndSettle();
    expect(find.text('Unable to load catalog.'), findsOneWidget);
    phase = 1;
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('No products available.'), findsOneWidget);
    phase = 2;
    await tester.tap(find.byTooltip('Refresh catalog'));
    await tester.pumpAndSettle();
    expect(find.text('INR 41.80'), findsOneWidget);
    expect(find.text('Tax rate: 18.00%'), findsOneWidget);
    expect(
        find.text(
            'Your customer price before tax. A new order is priced again by the server.'),
        findsOneWidget);
  });

  testWidgets(
      'catalog/orders/detail navigation and logout keep a stable router and clear private views',
      (tester) async {
    final harness = CustomerHarness((request) async {
      if (request.path == '/catalog') {
        return OfflineResponse(pageJson([productJson()]));
      }
      if (request.path == '/orders') {
        return OfflineResponse(pageJson([orderJson()]));
      }
      if (request.path.endsWith('/history')) {
        return const OfflineResponse(<Object?>[]);
      }
      return OfflineResponse(orderJson());
    });
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await tester.pumpWidget(UncontrolledProviderScope(
        container: harness.container, child: const SupplyOSCustomerApp()));
    await tester.pumpAndSettle();
    final router = harness.container.read(routerProvider);
    await tester.tap(find.text('Orders'));
    await tester.pumpAndSettle();
    expect(find.text('ORD-A'), findsOneWidget);
    await tester.tap(find.text('ORD-A'));
    await tester.pumpAndSettle();
    expect(find.text('Order details'), findsOneWidget);
    await tester.tap(find.byTooltip('Back to orders'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Sign out'));
    await tester.pumpAndSettle();
    expect(find.text('ORD-A'), findsNothing);
    expect(find.text('Sign in'), findsOneWidget);
    expect(harness.container.read(authProvider).key, isNull);
    expect(identical(router, harness.container.read(routerProvider)), isTrue);
    expect(find.text('Signed out of this app. Server logout confirmed.'),
        findsOneWidget);
  });

  testWidgets(
      'an unconfigured app has no loopback fallback or fake signed-in content',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
        overrides: [apiConfigProvider.overrideWithValue(null)],
        child: const SupplyOSCustomerApp()));
    await tester.pumpAndSettle();
    expect(find.text(const AppFailure(FailureKind.configuration).message),
        findsOneWidget);
    expect(find.text('My orders'), findsNothing);
    expect(tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed,
        isNull);
  });

  testWidgets(
      'orders remain usable on narrow screens with large text and exact long decimals',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final harness = CustomerHarness(
        (request) async => OfflineResponse(pageJson([orderJson()])));
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await tester.pumpWidget(UncontrolledProviderScope(
        container: harness.container,
        child: MaterialApp(
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: const TextScaler.linear(2)),
            child: child!,
          ),
          home: const OrdersScreen(),
        )));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('INR 1234567890123.4567890'), findsOneWidget);
  });
}
