import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_admin/core/navigation.dart';
import 'package:supplyos_admin/core/providers.dart';
import 'package:supplyos_core/supplyos_core.dart';

const userId = '11111111-1111-4111-8111-111111111111';
const otherUserId = '11111111-1111-4111-8111-111111111112';
const tenantId = '22222222-2222-4222-8222-222222222222';
const otherTenantId = '22222222-2222-4222-8222-222222222223';
const productId = '33333333-3333-4333-8333-333333333333';
const otherProductId = '33333333-3333-4333-8333-333333333334';
const warehouseId = '44444444-4444-4444-8444-444444444444';
const rackId = '44444444-4444-4444-8444-444444444445';
const shelfId = '44444444-4444-4444-8444-444444444446';
const orderId = '55555555-5555-4555-8555-555555555555';
const customerId = '66666666-6666-4666-8666-666666666666';
const otherCustomerId = '66666666-6666-4666-8666-666666666667';
const deliveryId = '77777777-7777-4777-8777-777777777777';
const partnerId = '88888888-8888-4888-8888-888888888888';
const tierId = '99999999-9999-4999-8999-999999999999';
const recordId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const timestamp = '2026-11-16T10:00:00Z';
const scopeFixture = SessionKey(userId, tenantId, ownerRole, 1);
const keyFixture = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

Map<String, Object?> userJson({
  String role = ownerRole,
  String id = userId,
  String tenant = tenantId,
}) => {
  'id': id,
  'tenant_id': tenant,
  'email': 'owner@fixture.test',
  'full_name': 'Fixture Owner',
  'role': role,
};
Map<String, Object?> productJson() => {
  'id': productId,
  'sku': 'SKU-1',
  'name': 'Fixture Rice',
  'unit': 'pcs',
  'pack_size': '1.000',
  'base_price': '12.50',
  'mrp': null,
  'gst_rate': '5.00',
  'reorder_level': 0,
  'low_stock_threshold': 10,
  'is_active': true,
  'description': null,
  'barcode': null,
  'hsn_code': null,
  'category_id': null,
  'image_url': null,
};
Map<String, Object?> categoryJson() => {
  'id': recordId,
  'name': 'Staples',
  'parent_id': null,
};
Map<String, Object?> warehouseJson() => {
  'id': warehouseId,
  'code': 'WH-1',
  'name': 'Central',
  'address': null,
  'city': null,
  'state': null,
  'pincode': null,
  'is_active': true,
};
Map<String, Object?> rackJson() => {
  'id': rackId,
  'warehouse_id': warehouseId,
  'code': 'R-1',
  'label': 'Main rack',
};
Map<String, Object?> shelfJson() => {
  'id': shelfId,
  'warehouse_id': warehouseId,
  'rack_id': rackId,
  'code': 'S-1',
  'label': 'Top shelf',
};
Map<String, Object?> inventoryJson() => {
  'id': recordId,
  'product_id': productId,
  'product_sku': 'SKU-1',
  'product_name': 'Fixture Rice',
  'warehouse_id': warehouseId,
  'warehouse_name': 'Central',
  'rack_id': null,
  'shelf_id': null,
  'batch_id': null,
  'quantity': '10.000',
  'reserved_qty': '1.000',
  'available_qty': '9.000',
  'in_transit_qty': '0.000',
  'damaged_qty': '0.000',
  'low_stock': false,
};
Map<String, Object?> inventoryStatsJson() => {
  'total_products': 1,
  'low_stock': 0,
  'out_of_stock': 0,
  'total_inventory_value': '125.00',
  'total_reserved': '1.000',
};
Map<String, Object?> customerJson() => {
  'id': customerId,
  'code': 'CUS-1',
  'name': 'Fixture Shop',
  'business_name': null,
  'gstin': null,
  'phone': null,
  'email': null,
  'address': null,
  'city': null,
  'state': null,
  'pincode': null,
  'customer_type': 'cash',
  'credit_limit': '100.00',
  'outstanding': '10.00',
  'credit_held': '5.00',
  'cash_funded_pending': '0.00',
  'credit_exposure': '15.00',
  'available_credit': '85.00',
  'advance_balance': '0.00',
  'price_tier': null,
  'is_active': true,
};
Map<String, Object?> orderLineJson() => {
  'id': recordId,
  'product_id': productId,
  'product_sku': 'SKU-1',
  'product_name': 'Fixture Rice',
  'quantity': '1.000',
  'unit_price': '12.50',
  'gst_rate': '5.00',
  'line_subtotal': '12.50',
  'line_tax': '0.63',
  'line_total': '13.13',
};
Map<String, Object?> orderJson() => {
  'id': orderId,
  'order_number': 'SO-1001',
  'customer_id': customerId,
  'warehouse_id': warehouseId,
  'status': 'pending',
  'channel': 'admin',
  'subtotal': '12.50',
  'tax_total': '0.63',
  'discount_total': '0.00',
  'grand_total': '13.13',
  'amount_paid': '0.00',
  'payment_mode': 'cash',
  'credit_hold_amount': '0.00',
  'payment_status': 'unpaid',
  'amount_due': '13.13',
  'scheduled_delivery_date': null,
  'delivery_address': null,
  'notes': null,
  'created_at': timestamp,
  'confirmed_at': null,
  'delivered_at': null,
  'items': [orderLineJson()],
};
Map<String, Object?> orderStatsJson() => {
  'total_orders': 1,
  'pending': 1,
  'confirmed': 0,
  'reserved': 0,
  'out_for_delivery': 0,
  'delivered_today': 0,
  'revenue_today': '0.00',
};
Map<String, Object?> deliveryJson() => {
  'id': deliveryId,
  'order_id': orderId,
  'partner_id': partnerId,
  'scheduled_date': '2026-11-16',
  'priority': 5,
  'otp_verified': false,
  'signature_url': null,
  'proof_photo_url': null,
  'cash_collected': '0.00',
  'upi_collected': '0.00',
  'started_at': null,
  'completed_at': null,
};
Map<String, Object?> paymentJson() => {
  'id': recordId,
  'customer_id': customerId,
  'order_id': orderId,
  'amount': '13.13',
  'mode': 'cash',
  'allocation_kind': 'order_payment',
  'reference': null,
  'note': null,
  'created_at': timestamp,
};
Map<String, Object?> staffJson() => {
  'id': partnerId,
  'full_name': 'Fixture Partner',
  'email': 'partner@fixture.test',
  'phone': null,
  'role': 'delivery_partner',
  'is_active': true,
  'created_at': timestamp,
};
Map<String, Object?> tierJson() => {
  'id': tierId,
  'name': 'Trade',
  'discount_pct': '10.00',
};
Map<String, Object?> overrideJson() => {
  'id': recordId,
  'customer_id': customerId,
  'product_id': productId,
  'price': '0.00',
};
Map<String, Object?> settingsJson() => {
  'tenant_id': tenantId,
  'company_name': 'Fixture Company',
  'currency_code': 'INR',
  'currency_symbol': 'Rs',
  'locale': 'en-IN',
  'values': {'allow_below_base_price': false, 'min_margin_pct': '0.00'},
  'applied_keys': null,
};
Map<String, Object?> capabilityJson() => {
  'free_only_mode': true,
  'can_request_summary': false,
  'summary_status': 'held_free_only',
};
Map<String, Object?> alertJson() => {
  'id': recordId,
  'category': 'inventory',
  'severity': 'warning',
  'title': 'Fixture low stock',
  'message': 'Check the server stock row.',
  'action_hint': 'Review replenishment',
  'resource_type': 'product',
  'resource_id': productId,
  'meta': {},
  'is_dismissed': false,
  'created_at': timestamp,
};
Map<String, Object?> pageJson(
  List<Object?> items, {
  int page = 1,
  int size = 50,
  int? total,
}) => {
  'items': items,
  'total': total ?? items.length,
  'page': page,
  'page_size': size,
};

class OfflineRequest {
  const OfflineRequest(this.options, this.body, this.bytes);
  final RequestOptions options;
  final Object? body;
  final String? bytes;
  String get path => options.uri.path.replaceFirst('/api/v1', '');
  String get method => options.method;
}

class OfflineResponse {
  const OfflineResponse(
    this.data, {
    this.status = 200,
    this.raw,
    this.headers = const {},
  });
  final Object? data;
  final int status;
  final String? raw;
  final Map<String, List<String>> headers;
  ResponseBody toBody() => ResponseBody.fromString(
    raw ?? (status == 204 ? '' : jsonEncode(data)),
    status,
    headers: {
      'content-type': ['application/json'],
      ...headers,
    },
  );
}

class OfflineBackend {
  OfflineBackend({this.role = ownerRole, this.handle});
  String role;
  Map<String, Object?>? identity;
  FutureOr<OfflineResponse?> Function(OfflineRequest)? handle;
  final requests = <OfflineRequest>[];
  final _seen = <(String, int), Completer<OfflineRequest>>{};
  DioSessionTransport transport(ApiConfig config) =>
      DioSessionTransport(config, adapterFactory: () => _Adapter(this));
  int count(String path, [String? method]) => requests
      .where((r) => r.path == path && (method == null || r.method == method))
      .length;
  Future<OfflineRequest> requested(String path, {int occurrence = 1}) {
    final found = requests.where((r) => r.path == path).toList();
    if (found.length >= occurrence) return Future.value(found[occurrence - 1]);
    return _seen.putIfAbsent((
      path,
      occurrence,
    ), Completer<OfflineRequest>.new).future;
  }

  Future<OfflineResponse> respond(OfflineRequest request) async {
    requests.add(request);
    final occurrence = count(request.path);
    final signal = _seen[(request.path, occurrence)];
    if (signal != null && !signal.isCompleted) signal.complete(request);
    final response = await handle?.call(request);
    if (response != null) return response;
    if (request.path == '/auth/me') {
      return OfflineResponse(identity ?? userJson(role: role));
    }
    if (request.path == '/auth/login') {
      return OfflineResponse(
        {'user': identity ?? userJson(role: role)},
        headers: {
          'set-cookie': [
            'access_token=fixture-admin; Path=/api/v1; Secure; HttpOnly',
            'refresh_token=fixture-refresh; Path=/api/v1/auth; Secure; HttpOnly',
          ],
        },
      );
    }
    if (request.path == '/auth/logout' || request.path == '/auth/refresh') {
      return const OfflineResponse({});
    }
    final page = request.options.queryParameters['page'] as int? ?? 1;
    if (request.method == 'GET') {
      return switch (request.path) {
        '/products' => OfflineResponse(pageJson([productJson()], page: page)),
        '/products/$productId' => OfflineResponse(productJson()),
        '/products/categories' => OfflineResponse([categoryJson()]),
        '/warehouses' => OfflineResponse([warehouseJson()]),
        '/warehouses/$warehouseId/racks' => OfflineResponse([rackJson()]),
        '/warehouses/racks/$rackId/shelves' => OfflineResponse([shelfJson()]),
        '/inventory' => OfflineResponse([inventoryJson()]),
        '/inventory/stats' => OfflineResponse(inventoryStatsJson()),
        '/inventory/movements' => const OfflineResponse([]),
        '/customers' => OfflineResponse(pageJson([customerJson()], page: page)),
        '/customers/$customerId' => OfflineResponse(customerJson()),
        '/customers/$customerId/ledger' => const OfflineResponse([]),
        '/customers/$customerId/prices' => const OfflineResponse([]),
        '/pricing/tiers' => OfflineResponse([tierJson()]),
        '/pricing/resolve' => const OfflineResponse({
          'customer_id': customerId,
          'product_id': productId,
          'price': '11.25',
        }),
        '/orders' => OfflineResponse(pageJson([orderJson()], page: page)),
        '/orders/$orderId' => OfflineResponse(orderJson()),
        '/orders/$orderId/history' => const OfflineResponse([]),
        '/orders/stats' => OfflineResponse(orderStatsJson()),
        '/deliveries' => OfflineResponse([deliveryJson()]),
        '/payments' => const OfflineResponse([]),
        '/staff' => OfflineResponse(pageJson([staffJson()], page: page)),
        '/settings' => OfflineResponse(settingsJson()),
        '/ai/capabilities' => OfflineResponse(capabilityJson()),
        '/ai/alerts' => const OfflineResponse([]),
        _ => const OfflineResponse({
          'detail': 'fixture unexpected route',
        }, status: 404),
      };
    }
    return const OfflineResponse({
      'detail': 'fixture unhandled mutation',
    }, status: 500);
  }
}

class _Adapter implements HttpClientAdapter {
  _Adapter(this.backend);
  final OfflineBackend backend;
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? stream,
    Future<void>? cancelFuture,
  ) async {
    final bytes = <int>[];
    if (stream != null) {
      await for (final chunk in stream) {
        bytes.addAll(chunk);
      }
    }
    final text = bytes.isEmpty ? null : utf8.decode(bytes);
    return (await backend.respond(
      OfflineRequest(options, text == null ? null : jsonDecode(text), text),
    )).toBody();
  }

  @override
  void close({bool force = false}) {}
}

ApiConfig fixtureConfig() =>
    ApiConfig.parse('https://admin.fixture.test/api/v1', isDebug: true);
SessionController fixtureSession(OfflineBackend backend) =>
    SessionController.withRolePolicy(
      config: fixtureConfig(),
      rolePolicy: SessionRolePolicy.admin,
      transportFactory: backend.transport,
    );
Future<SessionController> signedIn(OfflineBackend backend) async {
  final session = fixtureSession(backend);
  await session.login('fixture@fixture.test', 'fixture-only');
  return session;
}

Future<SessionState> settled(ProviderContainer container) async {
  var state = container.read(authProvider);
  final subscription = container.listen(authProvider, (_, _) {});
  try {
    for (var i = 0; i < 100; i++) {
      state = container.read(authProvider);
      if (state.phase != SessionPhase.checking) return state;
      await pumpEventQueue();
    }
    throw StateError('Fixture auth did not settle');
  } finally {
    subscription.close();
  }
}

Future<AppFailure> failureOf(Future<Object?> future) async {
  try {
    await future;
    fail('Expected failure');
  } catch (error) {
    if (error is AppFailure) return error;
    rethrow;
  }
}
