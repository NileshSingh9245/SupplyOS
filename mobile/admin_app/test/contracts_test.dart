import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_admin/core/contracts.dart';
import 'package:supplyos_admin/core/intents.dart';
import 'package:supplyos_admin/features/administration.dart';
import 'package:supplyos_admin/features/catalog.dart';
import 'package:supplyos_admin/features/customers.dart';
import 'package:supplyos_admin/features/deliveries.dart';
import 'package:supplyos_admin/features/finance.dart';
import 'package:supplyos_admin/features/locations.dart';
import 'package:supplyos_admin/features/orders.dart';
import 'package:supplyos_admin/features/pricing.dart';
import 'package:supplyos_admin/features/staff.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_backend.dart';

const productInput = ProductInput(
  sku: 'SKU-1',
  name: 'Fixture Rice',
  unit: 'pcs',
  basePrice: '12.50',
  gstRate: '5.00',
  packSize: '1.000',
);
const customerInput = CustomerInput(
  code: 'CUS-1',
  name: 'Fixture Shop',
  limit: '100.00',
);
OrderInput orderInput() => OrderInput(
  customerId: customerId,
  warehouseId: warehouseId,
  paymentMode: 'cash',
  lines: const [OrderLineInput(productId, '1.000')],
);
const receiptInput = PaymentInput(
  customerId: customerId,
  amount: '13.13',
  mode: 'cash',
  orderId: orderId,
);

void mutationCase<Q extends AdminInput, T>(
  String name,
  AdminCommand<Q, T> Function(SessionController) factory,
  Q input,
  Object? response,
  int status,
) {
  test(name, () async {
    late AdminCommand<Q, T> command;
    final backend = OfflineBackend(
      handle: (request) =>
          request.method != 'GET' && request.path == command.endpoint.path
          ? OfflineResponse(response, status: status)
          : null,
    );
    // The auth paths never inspect the uninitialized command.
    backend.handle = (request) => request.path.startsWith('/auth/')
        ? null
        : request.method != 'GET' && request.path == command.endpoint.path
        ? OfflineResponse(response, status: status)
        : null;
    final session = await signedIn(backend);
    addTearDown(session.dispose);
    command = factory(session);
    final registry = AdminIntents(session);
    addTearDown(registry.dispose);
    final result = await registry.submit(command, input);
    expect(result.statusCode, status);
    expect(result.value, isA<T>());
    expect(registry.owner(command).snapshot.phase, MutationPhase.succeeded);
    final sent = backend.requests.firstWhere(
      (request) =>
          request.path == command.endpoint.path && request.method != 'GET',
    );
    expect(sent.method, command.endpoint.method.name.toUpperCase());
    expect(sent.options.contentType, 'application/json');
    if (command.endpoint.supportsIdempotency) {
      expect(
        isUuid(sent.options.headers['X-Idempotency-Key'] as String),
        isTrue,
      );
    } else {
      expect(sent.options.headers.containsKey('X-Idempotency-Key'), isFalse);
    }
    expect(
      sent.options.headers.keys.any(
        (key) =>
            key.toLowerCase() == 'authorization' ||
            key.toLowerCase() == 'origin',
      ),
      isFalse,
    );
    expect(backend.count(command.endpoint.path, sent.method), 1);
  });
}

void main() {
  test('order currency uses only the server snapshot, never current tenant currency', () {
    expect(
      OrderRecord({...orderJson(), 'currency_code': 'USD'})
          .funding['Document currency'],
      'USD',
    );
    expect(
      OrderRecord(orderJson()).funding['Document currency'],
      'Unknown legacy currency',
    );
    expect(
      () => OrderRecord({...orderJson(), 'currency_code': 'invalid'}),
      throwsA(isA<AppFailure>()),
    );
  });
  final decoders =
      <String, ({Object Function(Object?) parse, Map<String, Object?> data})>{
        'product': (parse: ProductRecord.new, data: productJson()),
        'category': (parse: CategoryRecord.new, data: categoryJson()),
        'warehouse': (parse: WarehouseRecord.new, data: warehouseJson()),
        'rack': (parse: RackRecord.new, data: rackJson()),
        'shelf': (parse: ShelfRecord.new, data: shelfJson()),
        'inventory row': (parse: InventoryRecord.new, data: inventoryJson()),
        'customer': (parse: CustomerRecord.new, data: customerJson()),
        'order': (parse: OrderRecord.new, data: orderJson()),
        'delivery': (parse: DeliveryRecord.new, data: deliveryJson()),
        'receipt': (parse: PaymentRecord.new, data: paymentJson()),
        'tier': (parse: TierRecord.new, data: tierJson()),
        'override': (parse: OverrideRecord.new, data: overrideJson()),
        'staff': (parse: StaffRecord.new, data: staffJson()),
        'alert': (parse: AlertRecord.new, data: alertJson()),
      };
  for (final entry in decoders.entries) {
    test(
      '${entry.key} DTO accepts its actual JSON contract and rejects a malformed ID',
      () {
        expect(entry.value.parse(entry.value.data), isNotNull);
        expect(
          () => entry.value.parse({...entry.value.data, 'id': 'untrusted-id'}),
          throwsA(isA<AppFailure>()),
        );
      },
    );
  }
  for (final entry in [
    (ProductRecord.new, productJson(), 'base_price'),
    (InventoryRecord.new, inventoryJson(), 'quantity'),
    (CustomerRecord.new, customerJson(), 'credit_exposure'),
    (OrderRecord.new, orderJson(), 'amount_due'),
    (PaymentRecord.new, paymentJson(), 'amount'),
    (TierRecord.new, tierJson(), 'discount_pct'),
  ]) {
    test(
      '${entry.$3} accepts only server decimal text, never client floats',
      () {
        for (final value in [12.5, double.nan, null, 'NaN', {}, 'Infinity']) {
          expect(
            () => entry.$1({...entry.$2, entry.$3: value}),
            throwsA(isA<AppFailure>()),
          );
        }
      },
    );
  }
  test('customer balances are taken exactly from actual server fields without arithmetic', () {
    final customer = CustomerRecord({
      ...customerJson(),
      'credit_exposure': '777.777',
      'available_credit': '-41.2300',
      'advance_balance': '9.9999',
    });
    expect(customer.exposure.text, '777.777');
    expect(customer.headroom.text, '-41.2300');
    expect(customer.advance.text, '9.9999');
    expect(customer.balances['Signed balance'], '10.00');
    expect(customerInput.toJson().containsKey('credit_days'), isFalse);
    expect(customerInput.toJson().containsKey('contact_person'), isFalse);
  });
  test('decimal identity only compares text exactly, with no rounding or money rules', () {
    expect(decimalIdentity('00012.5000'), '12.5');
    expect(decimalIdentity('-0000.00'), '0');
    requireDecimalBinding(ServerDecimal.parse('12.50'), '12.5');
    expect(
      () => requireDecimalBinding(ServerDecimal.parse('12.51'), '12.5'),
      throwsA(isA<AppFailure>()),
    );
  });
  test('order request is typed legacy creation, never supplied price/total/quote authority', () {
    final body = orderInput().toJson();
    expect(body['channel'], 'admin');
    expect(
      body.keys.toSet().intersection({
        'tenant_id',
        'subtotal',
        'unit_price',
        'grand_total',
        'amount_due',
        'quote_id',
        'quote_proof',
      }),
      isEmpty,
    );
    expect(createOrderCommand.endpoint.expectedStatus, 201);
    expect(createOrderCommand.endpoint.path, '/orders');
    expect(
      () => OrderInput(
        customerId: customerId,
        warehouseId: warehouseId,
        lines: const [],
      ).toJson(),
      throwsA(isA<AppFailure>()),
    );
  });
  test('credit notes cannot masquerade as collected order funding', () {
    expect(
      () => const PaymentInput(
        customerId: customerId,
        amount: '1.00',
        mode: 'credit',
        orderId: orderId,
      ).toJson(),
      throwsA(isA<AppFailure>()),
    );
    expect(
      () => PaymentRecord({...paymentJson(), 'mode': 'credit'}),
      throwsA(isA<AppFailure>()),
    );
    expect(
      () => PaymentRecord({...paymentJson(), 'allocation_kind': 'credit_note'}),
      throwsA(isA<AppFailure>()),
    );
  });
  test('settings writes whitelist supported typed keys under the real patch envelope', () {
    final body = const SettingsInput('Fixture Company', false, '0.00').toJson();
    expect(body.keys, ['patch']);
    expect((body['patch']! as Map).keys.toSet(), {
      'company_name',
      'allow_below_base_price',
      'min_margin_pct',
    });
    expect((body['patch']! as Map).containsKey('currency_code'), isFalse);
    expect((body['patch']! as Map).containsKey('otp_length'), isFalse);
  });
  test(
    'AI capability never labels held/contradictory providers as available',
    () {
      expect(AICapability(capabilityJson()).canSummary, isFalse);
      expect(
        () => AICapability({...capabilityJson(), 'can_request_summary': true}),
        throwsA(isA<AppFailure>()),
      );
      expect(
        () => AnalysisRecord({
          'counts': {'low_stock': 1},
          'summary_status': 'queued',
        }),
        throwsA(isA<AppFailure>()),
      );
      expect(AlertRecord(alertJson()).severity, 'warning');
    },
  );
  test('private proof metadata is bound and is not an external or arbitrary binary URL', () {
    expect(
      DeliveryRecord({
        ...deliveryJson(),
        'signature_url':
            '/api/v1/deliveries/$deliveryId/proofs/$recordId/content',
      }).hasSignature,
      isTrue,
    );
    for (final ref in [
      'https://external.fixture.test/private',
      '/api/v1/deliveries/$orderId/proofs/$recordId',
      '/api/v1/deliveries/$deliveryId/proofs/------------------------------------',
      '/api/v1/deliveries/$deliveryId/proofs/$recordId?secret=private',
    ]) {
      expect(
        () => DeliveryRecord({...deliveryJson(), 'signature_url': ref}),
        throwsA(isA<AppFailure>()),
      );
    }
  });
  test(
    'timestamps and scheduled dates reject malformed or rolled-over data',
    () {
      expect(
        () =>
            OrderRecord({...orderJson(), 'created_at': '2026-02-30T10:00:00Z'}),
        throwsA(isA<AppFailure>()),
      );
      expect(
        () =>
            DeliveryRecord({...deliveryJson(), 'scheduled_date': '2026-02-30'}),
        throwsA(isA<AppFailure>()),
      );
      expect(
        () => StaffRecord({...staffJson(), 'is_active': 'true'}),
        throwsA(isA<AppFailure>()),
      );
    },
  );
  test(
    'all status actions follow the real web flow and remain exact HTTP 200',
    () {
      expect(orderActions('pending'), ['confirm', 'cancel']);
      expect(orderActions('confirmed'), ['reserve', 'cancel']);
      expect(orderActions('reserved'), ['pick', 'cancel']);
      expect(orderActions('picked'), ['pack', 'cancel']);
      expect(orderActions('packed'), ['dispatch', 'cancel']);
      expect(orderActions('out_for_delivery'), ['cancel']);
      expect(orderActions('paid'), isEmpty);
    },
  );

  mutationCase(
    'create product 201',
    (_) => productCommand(),
    productInput,
    productJson(),
    201,
  );
  mutationCase(
    'patch product 200',
    (_) => productCommand(productId),
    const ProductInput(
      name: 'Fixture Rice',
      unit: 'pcs',
      basePrice: '12.50',
      gstRate: '5.00',
      packSize: '1.000',
    ),
    productJson(),
    200,
  );
  mutationCase(
    'category creation 201',
    (_) => categoryCommand,
    const CategoryInput('Staples', null),
    categoryJson(),
    201,
  );
  mutationCase(
    'warehouse creation 201',
    (_) => warehouseCommand,
    const WarehouseInput('WH-1', 'Central', '', '', '', ''),
    warehouseJson(),
    201,
  );
  mutationCase(
    'rack creation 201 binds warehouse',
    (_) => rackCommand(warehouseId),
    const RackInput(warehouseId, 'R-1', 'Main rack'),
    rackJson(),
    201,
  );
  mutationCase(
    'shelf creation 201 binds rack and warehouse',
    (_) => shelfCommand(warehouseId, rackId),
    const ShelfInput(rackId, 'S-1', 'Top shelf'),
    shelfJson(),
    201,
  );
  mutationCase(
    'stock adjustment 200 trusts server quantity and binds location',
    (_) => adjustmentCommand,
    const AdjustmentInput(
      productId: productId,
      warehouseId: warehouseId,
      delta: '2.000',
    ),
    inventoryJson(),
    200,
  );
  mutationCase(
    'customer creation 201',
    (_) => customerCommand(),
    customerInput,
    customerJson(),
    201,
  );
  mutationCase(
    'customer contact credit edit 200',
    (_) => customerCommand(customerId),
    const CustomerInput(name: 'Fixture Shop', limit: '100.00'),
    customerJson(),
    200,
  );
  mutationCase(
    'tier creation 201',
    (_) => tierCommand(),
    const TierInput('10.00', name: 'Trade'),
    tierJson(),
    201,
  );
  mutationCase(
    'tier discount edit 200',
    (_) => tierCommand(tierId),
    const TierInput('10.00'),
    tierJson(),
    200,
  );
  mutationCase(
    'tier assignment 200 proves UUID to immutable name with scoped GET',
    (session) => assignmentCommand(customerId, session),
    const TierAssignmentInput(tierId),
    {...customerJson(), 'price_tier': 'Trade'},
    200,
  );
  mutationCase(
    'zero override 200 is not ignored',
    (_) => overrideCommand(customerId),
    const OverrideInput(productId, '0'),
    overrideJson(),
    200,
  );
  mutationCase(
    'override removal accepts only empty 204',
    (_) => removeOverrideCommand(customerId, productId),
    const NoInput(),
    null,
    204,
  );
  mutationCase(
    'create pending order 201 with UUID header',
    (_) => createOrderCommand,
    orderInput(),
    orderJson(),
    201,
  );
  for (final action in actionStatuses.entries) {
    mutationCase(
      'order ${action.key} 200',
      (_) => orderActionCommand(orderId, action.key),
      const OrderActionInput(''),
      {...orderJson(), 'status': action.value},
      200,
    );
  }
  mutationCase(
    'owner delivery assignment 200',
    (_) => assignDeliveryCommand(DeliveryRecord(deliveryJson())),
    const DeliveryAssignmentInput(partnerId, '2026-11-16', 5),
    deliveryJson(),
    200,
  );
  mutationCase(
    'start delivery 200 never completes it',
    (_) => startDeliveryCommand(DeliveryRecord(deliveryJson())),
    const NoInput(),
    {...deliveryJson(), 'started_at': timestamp},
    200,
  );
  mutationCase(
    'staff lifecycle 200 excludes credentials',
    (_) => staffCommand(partnerId),
    const StaffInput('Fixture Partner', '', 'delivery_partner', true),
    staffJson(),
    200,
  );
  mutationCase(
    'revoke staff sessions 200',
    (_) => revokeStaffCommand(partnerId),
    const NoInput(),
    {'message': 'Staff sessions revoked', 'current_actor_revoked': false},
    200,
  );
  mutationCase(
    'manual order receipt 201 with UUID header',
    (_) => paymentCommand,
    receiptInput,
    paymentJson(),
    201,
  );
  mutationCase(
    'typed supported settings 200 binds scope and applied keys',
    (_) => settingsCommand,
    const SettingsInput('Fixture Company', false, '0.00'),
    {
      ...settingsJson(),
      'applied_keys': [
        'company_name',
        'allow_below_base_price',
        'min_margin_pct',
      ],
    },
    200,
  );
  mutationCase(
    'real AI rule checks 200 without summary request',
    (_) => analyzeCommand,
    const NoInput(),
    {
      'counts': {'low_stock': 1, 'dead_stock': 0, 'credit_risk': 0},
      'summary_status': 'not_requested',
    },
    200,
  );
  mutationCase(
    'dismiss actual alert 200',
    (_) => dismissAlertCommand(recordId),
    const NoInput(),
    {...alertJson(), 'is_dismissed': true},
    200,
  );

  for (final status in [200, 202, 204]) {
    test(
      'create order rejects unexpected $status and remains uncertain',
      () async {
        final backend = OfflineBackend(
          handle: (request) =>
              request.path == '/orders' && request.method == 'POST'
              ? OfflineResponse(orderJson(), status: status)
              : null,
        );
        final session = await signedIn(backend);
        addTearDown(session.dispose);
        final registry = AdminIntents(session);
        addTearDown(registry.dispose);
        final failure = await failureOf(
          registry.submit(createOrderCommand, orderInput()),
        );
        expect(failure.isOutcomeUncertain, isTrue);
        expect(
          registry.owner(createOrderCommand).snapshot.phase,
          MutationPhase.uncertain,
        );
        expect(backend.count('/orders', 'POST'), 1);
      },
    );
  }
  test(
    'unexpected receipt/customer/product bodies never publish fake success',
    () async {
      final command = createOrderCommand;
      final backend = OfflineBackend(
        handle: (request) =>
            request.path == '/orders' && request.method == 'POST'
            ? OfflineResponse({
                ...orderJson(),
                'customer_id': otherCustomerId,
              }, status: 201)
            : null,
      );
      final session = await signedIn(backend);
      addTearDown(session.dispose);
      final registry = AdminIntents(session);
      addTearDown(registry.dispose);
      final failure = await failureOf(registry.submit(command, orderInput()));
      expect(failure.isOutcomeUncertain, isTrue);
      expect(registry.owner(command).snapshot.response, isNull);
    },
  );
  test(
    'settings receipt cannot confirm another tenant or omitted applied keys',
    () async {
      final original = settingsCommand.endpoint.createRequest(
        const SettingsInput('Fixture Company', false, '0.00'),
        scope: scopeFixture,
      );
      await expectLater(
        original.decodeResponse(200, {
          ...settingsJson(),
          'tenant_id': otherTenantId,
        }),
        throwsA(isA<AppFailure>()),
      );
      await expectLater(
        original.decodeResponse(200, settingsJson()),
        throwsA(isA<AppFailure>()),
      );
    },
  );
  for (final status in [409, 422, 429]) {
    test(
      '$status private errors are typed and sanitized without backend input echo',
      () async {
        final backend = OfflineBackend(
          handle: (request) =>
              request.path == '/payments' && request.method == 'POST'
              ? OfflineResponse({
                  'detail': [
                    {
                      'input': 'private-fixture-input',
                      'msg': 'private-fixture-error',
                    },
                  ],
                }, status: status)
              : null,
        );
        final session = await signedIn(backend);
        addTearDown(session.dispose);
        final registry = AdminIntents(session);
        addTearDown(registry.dispose);
        final failure = await failureOf(
          registry.submit(paymentCommand, receiptInput),
        );
        expect(failure.statusCode, status);
        expect(failure.isOutcomeUncertain, isFalse);
        expect(failure.toString().contains('private-fixture'), isFalse);
      },
    );
  }
}
