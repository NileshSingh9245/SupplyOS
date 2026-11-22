import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_admin/core/forms.dart';
import 'package:supplyos_admin/core/navigation.dart';
import 'package:supplyos_admin/core/providers.dart';
import 'package:supplyos_admin/core/widgets.dart';
import 'package:supplyos_admin/features/catalog.dart';
import 'package:supplyos_admin/main.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_backend.dart';

Future<SessionController> widgetSession(
  WidgetTester tester,
  OfflineBackend backend,
) async => (await tester.runAsync(() => signedIn(backend)))!;

void adminWidgetTest(
  String description,
  Future<void> Function(WidgetTester) body,
) {
  testWidgets(description, (tester) async {
    final semantics = tester.ensureSemantics();
    try {
      await body(tester);
    } finally {
      semantics.dispose();
    }
  });
}

Future<void> frames(WidgetTester tester, [int count = 12]) async {
  for (var i = 0; i < count; i++) {
    await tester.pump(const Duration(milliseconds: 30));
  }
}

Future<void> tapVisible(WidgetTester tester, Finder target) async {
  FocusManager.instance.primaryFocus?.unfocus();
  await frames(tester, 2);
  await tester.ensureVisible(target);
  await frames(tester, 2);
  final root = Offset.zero & tester.view.physicalSize;
  expect(
    root.contains(tester.getCenter(target)),
    isTrue,
    reason: 'The action must be physically tappable after scrolling.',
  );
  await tester.tap(target);
  await frames(tester);
}

Future<ProviderContainer> pumpAdmin(
  WidgetTester tester,
  SessionController session, {
  String? path,
  Size size = const Size(1200, 1000),
  double scale = 1,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = scale;
  addTearDown(() async {
    await tester.pumpWidget(const SizedBox.shrink());
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.platformDispatcher.clearTextScaleFactorTestValue();
  });
  await tester.pumpWidget(
    ProviderScope(
      overrides: [authProvider.overrideWith((ref) => session)],
      child: const SupplyOSAdminApp(),
    ),
  );
  await frames(tester);
  final container = ProviderScope.containerOf(
    tester.element(find.byType(SupplyOSAdminApp)),
    listen: false,
  );
  if (path != null) {
    container.read(adminRouterProvider).go(path);
    await frames(tester);
  }
  return container;
}

void main() {
  adminWidgetTest(
    'category search filters actual records without a fake update endpoint',
    (tester) async {
      final backend = OfflineBackend();
      final session = await widgetSession(tester, backend);
      await pumpAdmin(tester, session, path: '/products/categories');
      expect(find.text('Staples'), findsOneWidget);
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Search categories'),
        'no-match',
      );
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await frames(tester);
      expect(find.text('No categories match this search.'), findsOneWidget);
      expect(
        backend.requests.any(
          (request) =>
              request.method == 'PATCH' && request.path.contains('categories'),
        ),
        isFalse,
      );
    },
  );
  for (final role in adminRoles) {
    adminWidgetTest(
      '$role gets native filtered home and tablet navigation rail',
      (tester) async {
        final session = await widgetSession(tester, OfflineBackend(role: role));
        final container = await pumpAdmin(tester, session);
        expect(
          container
              .read(adminRouterProvider)
              .routeInformationProvider
              .value
              .uri
              .path,
          homeFor(role),
        );
        expect(
          MediaQuery.sizeOf(tester.element(find.byType(AdminFrame))).width,
          1200,
        );
        final rail = find.byWidgetPredicate(
          (widget) =>
              widget is Semantics &&
              widget.properties.label == 'Admin navigation rail',
        );
        expect(rail, findsOneWidget);
        expect(tester.getSemantics(rail).label, 'Admin navigation rail');
        expect(find.bySemanticsLabel('Admin navigation rail'), findsOneWidget);
        for (final destination in destinationsFor(role)) {
          expect(find.text(destination.label), findsWidgets);
        }
        for (final destination in adminDestinations.where(
          (destination) => !destination.roles.contains(role),
        )) {
          expect(find.text(destination.label), findsNothing);
        }
        expect(tester.takeException(), isNull);
      },
    );
  }
  adminWidgetTest(
    'manager cannot deep-link to private owner/accountant modules',
    (tester) async {
      final backend = OfflineBackend(role: managerRole);
      final session = await widgetSession(tester, backend);
      final container = await pumpAdmin(tester, session, path: '/staff');
      expect(
        container
            .read(adminRouterProvider)
            .routeInformationProvider
            .value
            .uri
            .path,
        '/inventory',
      );
      expect(backend.count('/staff'), 0);
      container.read(adminRouterProvider).go('/finance');
      await frames(tester);
      expect(backend.count('/payments'), 0);
      expect(tester.takeException(), isNull);
    },
  );
  for (final module in [
    '/products',
    '/warehouses',
    '/inventory',
    '/customers',
    '/pricing',
    '/orders',
    '/deliveries',
    '/finance',
    '/settings',
    '/ai-supervisor',
    '/staff',
  ]) {
    adminWidgetTest('$module loads its actual native server workflow', (
      tester,
    ) async {
      final backend = OfflineBackend();
      final session = await widgetSession(tester, backend);
      await pumpAdmin(tester, session, path: module);
      expect(
        backend.requests.where(
          (request) =>
              request.method == 'GET' && !request.path.startsWith('/auth/'),
        ),
        isNotEmpty,
      );
      expect(tester.takeException(), isNull);
    });
  }
  adminWidgetTest(
    'empty products are explicit, not a fabricated list or forever spinner',
    (tester) async {
      final backend = OfflineBackend(
        handle: (request) =>
            request.path == '/products' ? OfflineResponse(pageJson([])) : null,
      );
      final session = await widgetSession(tester, backend);
      await pumpAdmin(tester, session, path: '/products');
      expect(find.text('No products match this search.'), findsOneWidget);
      expect(find.text('Fixture Rice'), findsNothing);
    },
  );
  adminWidgetTest(
    'server failures show safe actionable read errors and retry',
    (tester) async {
      final backend = OfflineBackend(
        handle: (request) => request.path == '/products'
            ? const OfflineResponse({
                'detail': 'private-fixture-error',
              }, status: 503)
            : null,
      );
      final session = await widgetSession(tester, backend);
      await pumpAdmin(tester, session, path: '/products');
      expect(find.text('Retry server read'), findsOneWidget);
      expect(find.textContaining('private-fixture-error'), findsNothing);
      expect(
        find.text('The service is unavailable. Try again later.'),
        findsOneWidget,
      );
    },
  );
  adminWidgetTest(
    'confirmed mutations trigger an actual current scoped read refresh',
    (tester) async {
      var name = 'Original rice';
      final backend = OfflineBackend(
        handle: (request) {
          if (request.path == '/products/$productId') {
            if (request.method == 'PATCH') {
              name = 'Updated rice';
            }
            return OfflineResponse({...productJson(), 'name': name});
          }
          return null;
        },
      );
      final session = await widgetSession(tester, backend);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [authProvider.overrideWith((ref) => session)],
          child: MaterialApp(
            home: Scaffold(
              body: TaskPage(
                eyebrow: 'Test real refresh',
                title: 'Product',
                children: [
                  QueryPanel(
                    query: productQuery,
                    argument: productId,
                    builder: (product) => Text(product.name),
                  ),
                  IntentForm(
                    command: productCommand(productId),
                    fields: const [],
                    input: (_) => const ProductInput(
                      name: 'Updated rice',
                      unit: 'pcs',
                      basePrice: '12.50',
                      gstRate: '5.00',
                      packSize: '1.000',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
      await frames(tester);
      expect(find.text('Original rice'), findsOneWidget);
      await tester.tap(find.text('Save product'));
      await frames(tester);
      expect(backend.count('/products/$productId', 'PATCH'), 1);
      expect(
        backend.count('/products/$productId', 'GET'),
        greaterThanOrEqualTo(2),
      );
      expect(find.text('Updated rice'), findsOneWidget);
      expect(find.text('Original rice'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
  adminWidgetTest(
    'uncertain form close/edit/reopen retains and displays original body',
    (tester) async {
      final backend = OfflineBackend(
        handle: (request) =>
            request.path == '/products' && request.method == 'POST'
            ? const OfflineResponse({}, status: 503)
            : null,
      );
      final session = await widgetSession(tester, backend);
      final container = await pumpAdmin(
        tester,
        session,
        path: '/products/new',
        size: const Size(1000, 1200),
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'SKU'),
        'FROZEN-SKU',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Product name'),
        'Frozen product',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Base price'),
        '12.50',
      );
      final submit = find.text('Create product');
      await tapVisible(tester, submit);
      final owner = container
          .read(adminIntentsProvider)
          .owner(productCommand());
      final original = owner.snapshot.request!;
      expect(owner.snapshot.phase, MutationPhase.uncertain);
      expect(
        tester
            .widget<TextFormField>(
              find.widgetWithText(TextFormField, 'Product name'),
            )
            .enabled,
        isFalse,
      );
      container.read(adminRouterProvider).go('/products');
      await frames(tester);
      container.read(adminRouterProvider).go('/products/new');
      await frames(tester);
      expect(identical(owner.snapshot.request, original), isTrue);
      expect(
        tester
            .widget<TextFormField>(
              find.widgetWithText(TextFormField, 'Product name'),
            )
            .controller!
            .text,
        'Frozen product',
      );
      expect(backend.count('/products', 'POST'), 1);
      expect(owner.snapshot.canRetry, isFalse);
      expect(tester.takeException(), isNull);
    },
  );
  adminWidgetTest(
    'exact server due button updates visible receipt amount, no hidden value',
    (tester) async {
      final backend = OfflineBackend();
      final session = await widgetSession(tester, backend);
      await pumpAdmin(
        tester,
        session,
        path: '/finance',
        size: const Size(1100, 1600),
      );
      await tester.tap(find.text('Choose Receipt customer'));
      await frames(tester);
      await tester.tap(find.text('CUS-1 / Fixture Shop'));
      await frames(tester);
      final choose = find.text('Choose order allocation (optional)');
      await tapVisible(tester, choose);
      await tester.tap(find.text('SO-1001'));
      await frames(tester);
      final due = find.text('Use exact server amount due');
      await tapVisible(tester, due);
      final amount = tester.widget<TextFormField>(
        find.widgetWithText(TextFormField, 'Receipt amount'),
      );
      expect(amount.controller!.text, '13.13');
      expect(backend.count('/payments', 'POST'), 0);
      expect(tester.takeException(), isNull);
    },
  );
  adminWidgetTest(
    'private form and picker data disappear across account replacement',
    (tester) async {
      final backend = OfflineBackend();
      final session = await widgetSession(tester, backend);
      final container = await pumpAdmin(tester, session, path: '/customers');
      expect(find.text('Fixture Shop'), findsOneWidget);
      backend.identity = userJson(
        id: otherUserId,
        tenant: otherTenantId,
        role: managerRole,
      );
      await tester.runAsync(
        () => session.login('other@fixture.test', 'fixture-only'),
      );
      await frames(tester);
      expect(
        container
            .read(adminRouterProvider)
            .routeInformationProvider
            .value
            .uri
            .path,
        '/inventory',
      );
      expect(find.text('Fixture Shop'), findsNothing);
      expect(find.text('Customers'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
  adminWidgetTest('account-bound modal never republishes private old labels', (
    tester,
  ) async {
    final backend = OfflineBackend();
    final session = await widgetSession(tester, backend);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [authProvider.overrideWith((ref) => session)],
        child: MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: FilledButton(
                onPressed: () => showAccountSheet(
                  context,
                  builder: (_) => const Text('Private old account label'),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Open'));
    await frames(tester);
    expect(find.text('Private old account label'), findsOneWidget);
    backend.identity = userJson(id: otherUserId, tenant: otherTenantId);
    await tester.runAsync(
      () => session.login('other@fixture.test', 'fixture-only'),
    );
    await frames(tester);
    expect(find.text('Private old account label'), findsNothing);
    expect(
      find.text('This account session ended. Close this view.'),
      findsOneWidget,
    );
    await tester.pumpWidget(const SizedBox.shrink());
  });
  adminWidgetTest(
    'logout removes private data and returns actionable native sign-in',
    (tester) async {
      final backend = OfflineBackend();
      final session = await widgetSession(tester, backend);
      await pumpAdmin(tester, session, path: '/customers');
      await tester.tap(
        find.byTooltip('Sign out and discard this account scope'),
      );
      await frames(tester);
      expect(find.text('Fixture Shop'), findsNothing);
      expect(find.text('Email'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);
      expect(
        find.text('Signed out of this app. Server logout confirmed.'),
        findsOneWidget,
      );
    },
  );
  for (final size in [const Size(360, 800), const Size(900, 1100)]) {
    adminWidgetTest(
      'responsive navigation and large text are keyboard-safe at ${size.width}',
      (tester) async {
        final session = await widgetSession(
          tester,
          OfflineBackend(role: managerRole),
        );
        await pumpAdmin(
          tester,
          session,
          path: '/products/new',
          size: size,
          scale: 2,
        );
        expect(tester.takeException(), isNull);
        final field = find.widgetWithText(TextFormField, 'Product name');
        await tapVisible(tester, field);
        expect(tester.takeException(), isNull);
        if (size.width < 760) {
          expect(find.byType(DrawerButton), findsOneWidget);
        } else {
          expect(
            find.bySemanticsLabel('Admin navigation rail'),
            findsOneWidget,
          );
        }
      },
    );
  }
  adminWidgetTest(
    'manager delivery page never reads owner-only staff or exposes OTP/proof completion',
    (tester) async {
      final backend = OfflineBackend(
        role: managerRole,
        handle: (request) => request.path == '/orders/$orderId'
            ? OfflineResponse({...orderJson(), 'status': 'out_for_delivery'})
            : null,
      );
      final session = await widgetSession(tester, backend);
      await pumpAdmin(tester, session, path: '/deliveries/$deliveryId');
      expect(backend.count('/staff'), 0);
      expect(
        backend.requests.any((request) => request.path.contains('/proofs/')),
        isFalse,
      );
      expect(find.text('Complete delivery'), findsNothing);
      expect(find.text('Verify OTP'), findsNothing);
      expect(
        find.textContaining('Manager assignment selection is held'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );
}
