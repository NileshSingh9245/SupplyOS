import 'dart:async';

import 'package:supplyos_core/supplyos_core.dart';

import '../../../packages/supplyos_core/test/support/offline_http.dart';
import 'customer_fixtures.dart';

const customerAId = '99999999-9999-4999-8999-999999999999';
const customerBId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const productAId = '88888888-8888-4888-8888-888888888888';
const productBId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const categoryId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const warehouseId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const inactiveWarehouseId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const paymentId = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
const quoteId = '12345678-1234-4234-8234-123456789012';

String requestKey(OfflineRequest request) => request.options.headers.entries
    .singleWhere((entry) => entry.key.toLowerCase() == 'x-idempotency-key')
    .value as String;

Map<String, Object?> workflowProduct(
        {String id = productAId, String name = 'Warehouse rice'}) =>
    {
      ...productJson(name: name),
      'id': id,
      'sku': id == productAId ? 'RICE-01' : 'SOAP-01',
      'unit': 'kg',
      'price': '41.80',
      'gst_rate': '5.00',
      'currency_code': 'USD',
    };

Map<String, Object?> workflowDetail({String id = productAId}) => {
      ...workflowProduct(id: id),
      'description': 'A server supplied description for your next supply run.',
      'barcode': 'REVIEW-001',
      'hsn_code': '1006',
      'category_id': categoryId,
      'image_url': null,
    };

Map<String, Object?> warehouseJson({bool active = true}) => {
      'id': active ? warehouseId : inactiveWarehouseId,
      'code': active ? 'CENTRAL' : 'RETIRED',
      'name': active ? 'Central warehouse' : 'Retired warehouse',
      'is_active': active,
      'address': 'Server warehouse address',
      'city': 'Warehouse city',
      'state': null,
      'pincode': null,
    };

Map<String, Object?> profileJson(
        {bool accountB = false, String type = 'credit'}) =>
    {
      'id': accountB ? customerBId : customerAId,
      'code': accountB ? 'CUS-B' : 'CUS-A',
      'name': accountB ? 'Account B' : 'Account A',
      'business_name': 'Server business',
      'gstin': null,
      'phone': null,
      'email': null,
      'address': accountB ? 'Address B' : 'Address A',
      'city': 'Server city',
      'state': null,
      'pincode': null,
      'customer_type': type,
      'is_active': true,
      'credit_limit': '1000.00',
      'outstanding': '37.25',
      'credit_held': '50.00',
      'cash_funded_pending': '18.00',
      'credit_exposure': '69.25',
      'available_credit': '930.75',
      'advance_balance': '7.0100',
      'price_tier': null,
    };

Map<String, Object?> ledgerJson({String note = 'Server ledger note'}) => {
      'id': quoteId,
      'debit': '37.2500',
      'credit': '0.00',
      'balance_after': '-7.0100',
      'reference_type': 'order',
      'reference_id': orderAId,
      'note': note,
      'created_at': '2026-11-16T12:00:00Z',
    };

Map<String, Object?> paymentJson(
        {bool accountB = false, String? order = orderAId}) =>
    {
      'id': paymentId,
      'customer_id': accountB ? customerBId : customerAId,
      'order_id': order,
      'amount': '37.2500',
      'mode': 'cash',
      'reference': 'Recorded reference',
      'note': 'Server receipt note',
      'created_at': '2026-11-16T12:30:00Z',
      'allocation_kind': 'order',
    };

Map<String, Object?> deliveryJson({String order = orderAId}) => {
      'id': quoteId,
      'order_id': order,
      'partner_id': null,
      'scheduled_date': '2026-11-17',
      'priority': 5,
      'otp_verified': false,
      'signature_url': null,
      'proof_photo_url': null,
      'cash_collected': '0.00',
      'upi_collected': '0.00',
      'started_at': '2026-11-16T13:00:00Z',
      'completed_at': null,
      'created_at': '2026-11-16T12:59:00Z',
    };

Map<String, Object?> quoteJson({
  String id = quoteId,
  Map<String, Object?>? body,
  List<String> blockers = const [],
  String expires = '2027-11-16T13:45:00Z',
}) {
  final request = JsonObject(body ??
      {
        'warehouse_id': warehouseId,
        'payment_mode': 'cash',
        'items': [
          {'product_id': productAId, 'quantity': '1.250'},
        ],
      });
  final lines = request.list('items', JsonObject.new);
  return {
    'id': id,
    'quote_proof': 'cXVvdGVf${id.replaceAll('-', '')}.c2lnbmF0dXJl',
    'warehouse_id': request.uuid('warehouse_id'),
    'expires_at': expires,
    'currency_code': 'USD',
    'payment_mode': request.string('payment_mode'),
    'items': [
      for (final line in lines)
        {
          'product_id': line.uuid('product_id'),
          'sku': line.uuid('product_id') == productAId ? 'RICE-01' : 'SOAP-01',
          'name': line.uuid('product_id') == productAId
              ? 'Warehouse rice'
              : 'Warehouse soap',
          'unit': 'kg',
          'quantity': line.string('quantity'),
          'unit_price': '41.80',
          'gst_rate': '5.00',
          'subtotal': '52.25',
          'tax': '2.61',
          'total': '54.86',
        }
    ],
    'subtotal': '52.25',
    'tax_total': '2.61',
    'grand_total': '54.86',
    'availability': [
      for (final line in lines)
        {
          'product_id': line.uuid('product_id'),
          'required_quantity': line.string('quantity'),
          'available_quantity':
              blockers.contains('insufficient_stock') ? '0.000' : '20.000',
        }
    ],
    'blockers': blockers,
  };
}

Map<String, Object?> checkoutJson(
    Map<String, Object?> quote, Map<String, Object?> body,
    {bool accountB = false}) {
  final json = JsonObject(quote);
  final items = json.list('items', JsonObject.new);
  return {
    ...orderJson(),
    'customer_id': accountB ? customerBId : customerAId,
    'warehouse_id': json.uuid('warehouse_id'),
    'quote_id': json.uuid('id'),
    'currency_code': json.string('currency_code'),
    'subtotal': json.string('subtotal'),
    'tax_total': json.string('tax_total'),
    'grand_total': json.string('grand_total'),
    'amount_due': json.string('grand_total'),
    'amount_paid': '0.00',
    'discount_total': '0.00',
    'payment_mode': json.string('payment_mode'),
    'credit_hold_amount': '0.00',
    'payment_status': 'unpaid',
    'delivery_address': body['delivery_address'],
    'scheduled_delivery_date': body['scheduled_delivery_date'],
    'notes': body['notes'],
    'items': [
      for (final entry in items.indexed)
        {
          'id': entry.$1 == 0 ? orderBId : productBId,
          'product_id': entry.$2.uuid('product_id'),
          'product_sku': entry.$2.string('sku'),
          'product_name': entry.$2.string('name'),
          'quantity': entry.$2.string('quantity'),
          'unit_price': entry.$2.string('unit_price'),
          'gst_rate': entry.$2.string('gst_rate'),
          'line_subtotal': entry.$2.string('subtotal'),
          'line_tax': entry.$2.string('tax'),
          'line_total': entry.$2.string('total'),
        }
    ],
  };
}

class WorkflowFixtures {
  FutureOr<OfflineResponse?> Function(OfflineRequest)? intercept;
  final quotes = <String, Map<String, Object?>>{};
  final quoteBodies = <String, Map<String, Object?>>{};
  final receipts = <String, Map<String, Object?>>{};
  List<String> blockers = const [];
  String expires = '2027-11-16T13:45:00Z';

  Future<OfflineResponse> handle(OfflineRequest request) async {
    final custom = await intercept?.call(request);
    if (custom != null) return custom;
    final isB = request.cookie.contains(userBId);
    if (request.path == '/auth/me') {
      return OfflineResponse(userJson(
          id: isB ? userBId : userAId, tenantId: isB ? tenantBId : tenantAId));
    }
    if (request.path == '/auth/refresh') return const OfflineResponse({});
    if (request.path == '/customers') {
      return OfflineResponse(pageJson([profileJson(accountB: isB)]));
    }
    if (request.path.endsWith('/ledger')) {
      return OfflineResponse([ledgerJson(note: isB ? 'Ledger B' : 'Ledger A')]);
    }
    if (request.path == '/payments') {
      return OfflineResponse([
        paymentJson(
            accountB: isB,
            order: request.options.queryParameters['order_id'] as String? ??
                orderAId)
      ]);
    }
    if (request.path == '/warehouses') {
      return OfflineResponse([warehouseJson(active: false), warehouseJson()]);
    }
    if (request.path == '/products/categories') {
      return const OfflineResponse([
        {'id': categoryId, 'name': 'Essentials', 'parent_id': null},
      ]);
    }
    if (request.path == '/catalog') {
      return OfflineResponse(pageJson([
        workflowProduct(
            id: isB ? productBId : productAId,
            name: isB ? 'Product B' : 'Warehouse rice'),
      ], page: request.options.queryParameters['page'] as int));
    }
    if (request.path.startsWith('/catalog/')) {
      return OfflineResponse(workflowDetail(id: request.path.split('/').last));
    }
    if (request.path == '/orders') {
      final customer = isB ? customerBId : customerAId;
      final own = receipts.values
          .where((receipt) => receipt['customer_id'] == customer)
          .toList();
      return OfflineResponse(pageJson([
        if (own.isNotEmpty)
          own.last
        else
          {
            ...orderJson(
                id: isB ? orderBId : orderAId, number: isB ? 'ORD-B' : 'ORD-A'),
            'customer_id': customer,
          },
      ], page: request.options.queryParameters['page'] as int));
    }
    if (request.path.endsWith('/history')) {
      return OfflineResponse([
        historyJson(),
        historyJson(
            id: orderBId,
            from: 'pending',
            to: 'reserved',
            at: '2026-11-16T12:00:00Z')
      ]);
    }
    if (request.path == '/deliveries') return OfflineResponse([deliveryJson()]);
    if (request.path == '/order-quotes') {
      final key = requestKey(request);
      final body =
          Map<String, Object?>.from(request.body! as Map<String, Object?>);
      quoteBodies.putIfAbsent(key, () => body);
      quotes.putIfAbsent(
          key,
          () => quoteJson(
              id: key, body: body, blockers: blockers, expires: expires));
      return OfflineResponse(quotes[key], status: 201);
    }
    if (request.path == '/orders/checkout') {
      final key = requestKey(request);
      final body = JsonObject(request.body);
      if (body.uuid('quote_id') != key ||
          !quotes.containsKey(key) ||
          body.string('quote_proof') != quotes[key]!['quote_proof']) {
        return const OfflineResponse({}, status: 422);
      }
      receipts.putIfAbsent(key,
          () => checkoutJson(quotes[key]!, quoteBodies[key]!, accountB: isB));
      return OfflineResponse(receipts[key], status: 201);
    }
    if (request.path.startsWith('/orders/')) {
      final id = request.path.split('/').last;
      final customer = isB ? customerBId : customerAId;
      final own = receipts.values
          .where((receipt) =>
              receipt['id'] == id && receipt['customer_id'] == customer)
          .toList();
      if (own.isNotEmpty) return OfflineResponse(own.single);
      if (id != (isB ? orderBId : orderAId)) {
        return const OfflineResponse({}, status: 404);
      }
      return OfflineResponse({
        ...orderJson(id: id, number: isB ? 'ORD-B' : 'ORD-A'),
        'customer_id': customer
      });
    }
    throw StateError('Unexpected fixture request');
  }
}
