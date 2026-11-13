import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_delivery/features/route/route_screen.dart';
import 'package:supplyos_delivery/main.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import '../../packages/supplyos_core/test/support/widget_harness.dart';
import 'support/delivery_fixtures.dart';

Future<void> showRoute(WidgetTester tester, DeliveryHarness harness) =>
    tester.pumpWidget(
      UncontrolledProviderScope(
          container: harness.container,
          child: const MaterialApp(home: RouteScreen())),
    );

void main() {
  testWidgets(
      'assigned route loading and empty states have refresh and visible logout',
      (tester) async {
    final reply = Completer<OfflineResponse>();
    final harness = DeliveryHarness((request) => reply.future);
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showRoute(tester, harness);
    await pumpUntil(
        tester, () => harness.backend.count('/deliveries/my-route') == 1);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.byTooltip('Sign out'), findsOneWidget);
    reply.complete(const OfflineResponse(<Object?>[]));
    await tester.pumpAndSettle();
    expect(find.text('No assigned stops.'), findsOneWidget);
    expect(find.byType(RefreshIndicator), findsOneWidget);
  });

  testWidgets('route error is sanitized and retry loads actual read-only stops',
      (tester) async {
    var available = false;
    final harness = DeliveryHarness((request) async => available
        ? OfflineResponse([stopJson(otp: true)])
        : const OfflineResponse({'detail': 'untrusted-fixture'}, status: 503));
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showRoute(tester, harness);
    await tester.pumpAndSettle();
    expect(find.text('Unable to load route.'), findsOneWidget);
    expect(find.textContaining('untrusted-fixture'), findsNothing);
    available = true;
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('Order 55555555'), findsOneWidget);
    expect(find.text('OTP verified: yes'), findsOneWidget);
    final tile = tester.widget<ListTile>(find.byType(ListTile));
    expect(tile.onTap, isNull);
    expect(tile.trailing, isNull);
    expect(find.text('Collect payment'), findsNothing);
    expect(find.text('Scan QR'), findsNothing);
    expect(harness.backend.count('/deliveries/my-route'), 2);
  });

  testWidgets(
      'malformed short order IDs produce a safe error, not a range crash',
      (tester) async {
    final harness = DeliveryHarness((request) async =>
        OfflineResponse([stopJson()..['order_id'] = 'tiny']));
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    await showRoute(tester, harness);
    await tester.pumpAndSettle();
    expect(find.text('Unable to load route.'), findsOneWidget);
    expect(find.text(const AppFailure(FailureKind.invalidResponse).message),
        findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'logout removes route data and accurately reports failed server logout',
      (tester) async {
    final harness =
        DeliveryHarness((request) async => OfflineResponse([stopJson()]));
    addTearDown(harness.dispose);
    await tester.runAsync(() => harness.login());
    final original = harness.backend.handle;
    harness.backend.handle = (request) => request.path == '/auth/logout'
        ? const OfflineResponse({}, status: 503)
        : original(request);
    await tester.pumpWidget(UncontrolledProviderScope(
        container: harness.container, child: const SupplyOSDeliveryApp()));
    await tester.pumpAndSettle();
    final router = harness.container.read(routerProvider);
    expect(find.text('Order 55555555'), findsOneWidget);
    await tester.tap(find.byTooltip('Sign out'));
    await tester.pumpAndSettle();
    expect(find.text('Order 55555555'), findsNothing);
    expect(find.text('Sign in'), findsOneWidget);
    expect(
        find.text(
            'Signed out of this app. Server logout could not be confirmed.'),
        findsOneWidget);
    expect(identical(router, harness.container.read(routerProvider)), isTrue);
  });

  testWidgets(
      'missing API configuration disables the delivery app rather than selecting localhost',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
        overrides: [apiConfigProvider.overrideWithValue(null)],
        child: const SupplyOSDeliveryApp()));
    await tester.pumpAndSettle();
    expect(find.text(const AppFailure(FailureKind.configuration).message),
        findsOneWidget);
    expect(find.text('Assigned route'), findsNothing);
    expect(tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed,
        isNull);
  });

  testWidgets('delivery route supports a narrow viewport and large text',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 480));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final harness =
        DeliveryHarness((request) async => OfflineResponse([stopJson()]));
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
          home: const RouteScreen(),
        )));
    await tester.pumpAndSettle();
    await pumpUntil(tester, () => find.byType(ListView).evaluate().isNotEmpty);
    await tester.scrollUntilVisible(
      find.text('Order 55555555'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(tester.takeException(), isNull);
    expect(find.text('Order 55555555'), findsOneWidget);
  });
}
