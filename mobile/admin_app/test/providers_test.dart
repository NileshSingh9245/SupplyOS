import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_admin/core/contracts.dart';
import 'package:supplyos_admin/core/intents.dart';
import 'package:supplyos_admin/core/navigation.dart';
import 'package:supplyos_admin/core/providers.dart';
import 'package:supplyos_admin/features/catalog.dart';
import 'package:supplyos_admin/features/customers.dart';
import 'package:supplyos_admin/features/finance.dart';
import 'package:supplyos_admin/features/locations.dart';
import 'package:supplyos_admin/features/orders.dart';
import 'package:supplyos_admin/features/staff.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'contracts_test.dart' show orderInput, receiptInput;
import 'support/offline_backend.dart';

Future<AsyncValue<T>> readResult<T, A>(
  ProviderContainer container,
  SessionQuery<T, A> query,
  A argument,
) async {
  final subscription = container.listen(query.provider(argument), (_, _) {});
  try {
    for (var i = 0; i < 100; i++) {
      final result = container.read(query.provider(argument));
      if (!result.isLoading) return result;
      await pumpEventQueue();
    }
    throw StateError('Fixture read did not settle');
  } finally {
    subscription.close();
  }
}

class ProbeInput implements AdminInput {
  ProbeInput(this.body);
  final Map<String, Object?> body;
  int encodes = 0;
  @override
  Map<String, Object?> toJson() {
    encodes++;
    return body;
  }
}

AdminCommand<ProbeInput, OrderRecord> probeCommand() => AdminCommand(
  slot: 'order:probe',
  title: 'Create pending order',
  route: '/orders/new',
  roles: operators,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/orders',
    expectedStatus: 201,
    supportsIdempotency: true,
    encode: (input) => input.toJson(),
    decode: createOrderCommand.endpoint.decode,
  ),
);

void main() {
  test('category detail uses the existing list contract and validates the selected ID', () async {
    final backend = OfflineBackend();
    final session = await signedIn(backend);
    final container = ProviderContainer(
      overrides: [authProvider.overrideWith((ref) => session)],
    );
    addTearDown(container.dispose);
    expect(
      (await readResult(container, categoryQuery, recordId)).requireValue.name,
      'Staples',
    );
    expect(
      (await readResult(container, categoryQuery, otherProductId)).hasError,
      isTrue,
    );
    expect(
      backend.requests
          .where((request) => request.path.contains('categories'))
          .every((request) => request.path == '/products/categories'),
      isTrue,
    );
  });
  test(
    'list reads publish strict DTOs and only endpoint-whitelisted parameters',
    () async {
      final backend = OfflineBackend();
      final session = await signedIn(backend);
      final container = ProviderContainer(
        overrides: [authProvider.overrideWith((ref) => session)],
      );
      addTearDown(container.dispose);
      final data = await readResult(container, productsQuery, (
        page: 2,
        q: 'rice',
      ));
      expect(data.requireValue.items.single.name, 'Fixture Rice');
      expect(backend.requests.last.options.queryParameters, {
        'page': 2,
        'page_size': 50,
        'q': 'rice',
      });
      expect(
        backend.requests.last.options.queryParameters.containsKey('tenant_id'),
        isFalse,
      );
    },
  );
  test(
    'unexpected pagination metadata is not accepted as the requested page',
    () async {
      final backend = OfflineBackend(
        handle: (request) => request.path == '/products'
            ? OfflineResponse(pageJson([productJson()], page: 1))
            : null,
      );
      final session = await signedIn(backend);
      final container = ProviderContainer(
        overrides: [authProvider.overrideWith((ref) => session)],
      );
      addTearDown(container.dispose);
      final data = await readResult(container, productsQuery, (page: 2, q: ''));
      expect(data.hasError, isTrue);
      expect(AppFailure.safe(data.error!).kind, FailureKind.invalidResponse);
    },
  );
  test('rack/shelf reads cannot publish foreign parent records', () async {
    final backend = OfflineBackend(
      handle: (request) => request.path.endsWith('/shelves')
          ? OfflineResponse([
              {...shelfJson(), 'warehouse_id': tenantId},
            ])
          : null,
    );
    final session = await signedIn(backend);
    final container = ProviderContainer(
      overrides: [authProvider.overrideWith((ref) => session)],
    );
    addTearDown(container.dispose);
    final data = await readResult(container, shelvesQuery, (
      warehouseId: warehouseId,
      rackId: rackId,
    ));
    expect(data.hasError, isTrue);
  });
  test('server low-stock filter is validated, not recalculated by client quantities', () async {
    final backend = OfflineBackend();
    final session = await signedIn(backend);
    final container = ProviderContainer(
      overrides: [authProvider.overrideWith((ref) => session)],
    );
    addTearDown(container.dispose);
    final data = await readResult(container, inventoryQuery, (
      q: '',
      warehouseId: null,
      lowOnly: true,
    ));
    expect(data.hasError, isTrue);
    expect(backend.requests.last.options.queryParameters, {
      'low_stock_only': true,
    });
  });
  test('owner-only staff provider never dispatches for manager', () async {
    final backend = OfflineBackend(role: managerRole);
    final session = await signedIn(backend);
    final container = ProviderContainer(
      overrides: [authProvider.overrideWith((ref) => session)],
    );
    addTearDown(container.dispose);
    final data = await readResult(container, staffQuery, (page: 1, q: ''));
    expect(data.hasError, isTrue);
    expect(AppFailure.safe(data.error!).kind, FailureKind.forbidden);
    expect(backend.count('/staff'), 0);
  });
  test('order filter validates original customer/status and keeps server due exact', () async {
    final backend = OfflineBackend();
    final session = await signedIn(backend);
    final container = ProviderContainer(
      overrides: [authProvider.overrideWith((ref) => session)],
    );
    addTearDown(container.dispose);
    final correct = await readResult(container, ordersQuery, (
      page: 1,
      status: 'pending',
      customerId: customerId,
    ));
    expect(correct.requireValue.items.single.due.text, '13.13');
    final wrong = await readResult(container, ordersQuery, (
      page: 1,
      status: 'pending',
      customerId: otherCustomerId,
    ));
    expect(wrong.hasError, isTrue);
  });
  test(
    'account transition discards old delayed customer publication and cache',
    () async {
      final old = Completer<OfflineResponse>();
      var reads = 0;
      final backend = OfflineBackend(
        handle: (request) => request.path == '/customers/$customerId'
            ? ++reads == 1
                  ? old.future
                  : OfflineResponse({
                      ...customerJson(),
                      'name': 'Account B shop',
                    })
            : null,
      );
      final session = await signedIn(backend);
      final container = ProviderContainer(
        overrides: [authProvider.overrideWith((ref) => session)],
      );
      addTearDown(container.dispose);
      final published = <String>[];
      final subscription = container.listen(
        customerQuery.provider(customerId),
        (_, next) {
          if (next.hasValue) published.add(next.requireValue.name);
        },
      );
      addTearDown(subscription.close);
      await backend.requested('/customers/$customerId');
      backend.identity = userJson(
        id: otherUserId,
        tenant: otherTenantId,
        role: accountantRole,
      );
      await session.login('other@fixture.test', 'fixture-only');
      old.complete(
        OfflineResponse({...customerJson(), 'name': 'Private account A shop'}),
      );
      await pumpEventQueue();
      final latest = await readResult(container, customerQuery, customerId);
      expect(latest.requireValue.name, 'Account B shop');
      expect(published, isNot(contains('Private account A shop')));
    },
  );
  test(
    'repository rechecks account after asynchronous typed decoder result',
    () async {
      final decoded = Completer<ProductRecord>();
      final started = Completer<void>();
      final backend = OfflineBackend();
      final session = await signedIn(backend);
      addTearDown(session.dispose);
      final attempt = failureOf(
        AdminRepository(session).read(
          '/products/$productId',
          session.snapshot.key!,
          CancelToken(),
          (_) {
            started.complete();
            return decoded.future;
          },
        ),
      );
      await started.future;
      backend.identity = userJson(id: otherUserId, tenant: otherTenantId);
      await session.login('other@fixture.test', 'fixture-only');
      decoded.complete(ProductRecord(productJson()));
      expect((await attempt).kind, FailureKind.superseded);
    },
  );
  for (final status in [408, 500, 503]) {
    test(
      'uncertain $status retains account-owned original and no automatic retry',
      () async {
        final backend = OfflineBackend(
          handle: (request) =>
              request.path == '/payments' && request.method == 'POST'
              ? OfflineResponse({}, status: status)
              : null,
        );
        final session = await signedIn(backend);
        addTearDown(session.dispose);
        final registry = AdminIntents(session);
        addTearDown(registry.dispose);
        final failure = await failureOf(
          registry.submit(paymentCommand, receiptInput),
        );
        await pumpEventQueue();
        expect(failure.isOutcomeUncertain, isTrue);
        expect(registry.unresolved.length, 1);
        expect(backend.count('/payments', 'POST'), 1);
        final owner = registry.owner(paymentCommand);
        expect(identical(owner, registry.owner(paymentCommand)), isTrue);
        final original = owner.snapshot.request!;
        expect(
          () => registry.submit(
            paymentCommand,
            const PaymentInput(
              customerId: otherCustomerId,
              amount: '2.00',
              mode: 'cash',
            ),
          ),
          throwsA(isA<AppFailure>()),
        );
        expect(identical(owner.snapshot.request, original), isTrue);
        expect(backend.count('/payments', 'POST'), 1);
      },
    );
  }
  test('explicit retry freezes deep mutable body and reuses exact original bytes/key', () async {
    var succeeds = false;
    final backend = OfflineBackend(
      handle: (request) => request.path == '/orders' && request.method == 'POST'
          ? succeeds
                ? OfflineResponse(orderJson(), status: 201)
                : const OfflineResponse({}, status: 503)
          : null,
    );
    final session = await signedIn(backend);
    addTearDown(session.dispose);
    final registry = AdminIntents(session);
    addTearDown(registry.dispose);
    final input = ProbeInput(orderInput().toJson());
    final command = probeCommand();
    await failureOf(registry.submit(command, input));
    final owner = registry.owner(command);
    final original = owner.snapshot.request!;
    final first = backend.requests.last;
    input.body['notes'] = 'changed after uncertainty';
    (input.body['items'] as List).first['quantity'] = '2.000';
    expect(() => registry.submit(command, input), throwsA(isA<AppFailure>()));
    expect(input.encodes, 1);
    succeeds = true;
    await registry.retry(command);
    expect(input.encodes, 1);
    expect(identical(owner.snapshot.request, original), isTrue);
    expect(backend.requests.last.bytes, first.bytes);
    expect(
      backend.requests.last.options.headers['X-Idempotency-Key'],
      first.options.headers['X-Idempotency-Key'],
    );
    expect(registry.revision, 1);
  });
  test('resource grouping prevents cancel/reserve variants from bypassing uncertainty', () async {
    final backend = OfflineBackend(
      handle: (request) => request.path == '/orders/$orderId/confirm'
          ? const OfflineResponse({}, status: 503)
          : null,
    );
    final session = await signedIn(backend);
    addTearDown(session.dispose);
    final registry = AdminIntents(session);
    addTearDown(registry.dispose);
    await failureOf(
      registry.submit(
        orderActionCommand(orderId, 'confirm'),
        const OrderActionInput(''),
      ),
    );
    expect(
      () => registry.submit(
        orderActionCommand(orderId, 'cancel'),
        const OrderActionInput('changed'),
      ),
      throwsA(
        isA<AppFailure>().having(
          (failure) => failure.kind,
          'kind',
          FailureKind.intentPending,
        ),
      ),
    );
    expect(backend.count('/orders/$orderId/cancel', 'POST'), 0);
  });
  test(
    'replay rejection does not erase the earlier uncertain payment',
    () async {
      var status = 503;
      final backend = OfflineBackend(
        handle: (request) =>
            request.path == '/payments' && request.method == 'POST'
            ? OfflineResponse({}, status: status)
            : null,
      );
      final session = await signedIn(backend);
      addTearDown(session.dispose);
      final registry = AdminIntents(session);
      addTearDown(registry.dispose);
      await failureOf(registry.submit(paymentCommand, receiptInput));
      final original = registry.owner(paymentCommand).snapshot.request;
      status = 409;
      expect(
        (await failureOf(registry.retry(paymentCommand))).isOutcomeUncertain,
        isTrue,
      );
      expect(
        registry.owner(paymentCommand).snapshot.phase,
        MutationPhase.uncertain,
      );
      expect(
        identical(registry.owner(paymentCommand).snapshot.request, original),
        isTrue,
      );
      expect(registry.revision, 0);
    },
  );
  test('logout clears retained original and prevents old replay into a new account', () async {
    final backend = OfflineBackend(
      handle: (request) =>
          request.path == '/payments' && request.method == 'POST'
          ? const OfflineResponse({}, status: 503)
          : null,
    );
    final session = await signedIn(backend);
    addTearDown(session.dispose);
    final registry = AdminIntents(session);
    addTearDown(registry.dispose);
    await failureOf(registry.submit(paymentCommand, receiptInput));
    final owner = registry.owner(paymentCommand);
    final original = owner.snapshot.request!;
    await session.logout();
    expect(registry.unresolved, isEmpty);
    expect(owner.mounted, isFalse);
    backend.identity = userJson(
      id: otherUserId,
      tenant: otherTenantId,
      role: accountantRole,
    );
    await session.login('other@fixture.test', 'fixture-only');
    await expectLater(session.mutate(original), throwsA(isA<AppFailure>()));
    expect(backend.count('/payments', 'POST'), 1);
  });
  test('new mutation joins a held renewal before dispatch and does not replay POST', () async {
    final identity = Completer<OfflineResponse>();
    var productReads = 0;
    final backend = OfflineBackend(
      handle: (request) {
        if (request.path == '/products' && ++productReads == 1) {
          return const OfflineResponse({}, status: 401);
        }
        if (request.path == '/auth/me') return identity.future;
        if (request.path == '/orders' && request.method == 'POST') {
          return OfflineResponse(orderJson(), status: 201);
        }
        return null;
      },
    );
    final session = await signedIn(backend);
    addTearDown(session.dispose);
    final registry = AdminIntents(session);
    addTearDown(registry.dispose);
    final read = session.get('/products', scope: session.snapshot.key!);
    await backend.requested('/auth/me');
    final write = registry.submit(createOrderCommand, orderInput());
    await pumpEventQueue();
    expect(backend.count('/orders', 'POST'), 0);
    identity.complete(OfflineResponse(userJson()));
    await read;
    await write;
    expect(backend.count('/orders', 'POST'), 1);
  });
  test('non-idempotent stock mutation cannot offer automatic or explicit POST replay', () async {
    final backend = OfflineBackend(
      handle: (request) => request.path == '/inventory/adjust'
          ? const OfflineResponse({}, status: 503)
          : null,
    );
    final session = await signedIn(backend);
    addTearDown(session.dispose);
    final registry = AdminIntents(session);
    addTearDown(registry.dispose);
    await failureOf(
      registry.submit(
        adjustmentCommand,
        const AdjustmentInput(
          productId: productId,
          warehouseId: warehouseId,
          delta: '2.000',
        ),
      ),
    );
    expect(registry.owner(adjustmentCommand).snapshot.canRetry, isFalse);
    expect(
      () => registry.retry(adjustmentCommand),
      throwsA(
        isA<AppFailure>().having(
          (failure) => failure.kind,
          'kind',
          FailureKind.retryUnsafe,
        ),
      ),
    );
    expect(backend.count('/inventory/adjust', 'POST'), 1);
  });
  test(
    'generic credentials/OTP are rejected and never enter retained requests',
    () async {
      final session = await signedIn(OfflineBackend());
      addTearDown(session.dispose);
      final registry = AdminIntents(session);
      addTearDown(registry.dispose);
      final input = ProbeInput({
        ...orderInput().toJson(),
        'password': 'private-fixture-input',
      });
      final command = probeCommand();
      expect(
        () => registry.submit(command, input),
        throwsA(
          isA<AppFailure>().having(
            (failure) => failure.kind,
            'kind',
            FailureKind.invalidRequest,
          ),
        ),
      );
      expect(registry.owner(command).snapshot.request, isNull);
    },
  );
}
