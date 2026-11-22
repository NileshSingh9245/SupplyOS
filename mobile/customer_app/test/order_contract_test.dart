import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_customer/core/formatters.dart';
import 'package:supplyos_customer/features/catalog/product.dart';
import 'package:supplyos_customer/features/orders/order.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import 'support/customer_fixtures.dart';

void main() {
  test(
      'OrderOut and item fields retain exact Decimal strings, never derived totals',
      () {
    final json = orderJson();
    final order = Order.fromJson(json);
    expect(order.id, orderAId);
    expect(order.customerId, userAId);
    expect(order.warehouseId, tenantAId);
    expect(order.channel, 'app');
    expect(order.paymentMode, 'credit');
    expect(order.subtotal.text, json['subtotal']);
    expect(order.taxTotal.text, json['tax_total']);
    expect(order.discountTotal.text, json['discount_total']);
    expect(order.grandTotal.text, json['grand_total']);
    expect(order.amountPaid.text, json['amount_paid']);
    expect(order.amountDue.text, json['amount_due']);
    expect(order.creditHoldAmount.text, json['credit_hold_amount']);
    expect(formatINR(order.grandTotal), 'INR 1234567890123.4567890');
    expect(order.items.single.quantity.text, '2.000');
    expect(order.items.single.unitPrice.text, '123.4500');
    expect(order.items.single.gstRate.text, '18.000');
    expect(order.items.single.lineSubtotal.text, '246.9000');
    expect(order.items.single.lineTax.text, '44.4420');
    expect(order.items.single.lineTotal.text, '291.3420');
    expect(() => order.items.clear(), throwsUnsupportedError);
  });

  test(
      'nullable order fields stay nullable and a literal address is not invented JSON',
      () {
    final json = orderJson();
    for (final field in [
      'scheduled_delivery_date',
      'delivery_address',
      'notes',
      'confirmed_at',
      'delivered_at'
    ]) {
      json[field] = null;
    }
    final order = Order.fromJson(json);
    expect(order.scheduledDeliveryDate, isNull);
    expect(order.deliveryAddress, isNull);
    expect(order.notes, isNull);
    expect(order.confirmedAt, isNull);
    expect(order.deliveredAt, isNull);
    expect(formatDate(order.scheduledDeliveryDate), 'Not scheduled');
    final withAddress = Order.fromJson(orderJson());
    expect(withAddress.deliveryAddress, 'Fixture address\nFixture city');
    expect(withAddress.scheduledDeliveryDate!.text, '2026-11-12');
    expect(
        () => Order.fromJson({
              ...orderJson(),
              'delivery_address': {'line1': 'not the contract'}
            }),
        throwsA(isA<AppFailure>()));
  });

  test(
      'additive fields and unknown order/payment statuses are safe read-only data',
      () {
    final order = Order.fromJson({
      ...orderJson(),
      'status': 'future_review',
      'payment_status': 'future_status',
      'added_server_field': true
    });
    expect(order.status, 'future_review');
    expect(statusLabel(order.status), 'Other status: future_review');
    expect(statusLabel(order.paymentStatus), 'Other status: future_status');
  });

  for (final field in [
    'id',
    'order_number',
    'customer_id',
    'warehouse_id',
    'status',
    'channel',
    'subtotal',
    'tax_total',
    'discount_total',
    'grand_total',
    'amount_paid',
    'payment_mode',
    'credit_hold_amount',
    'payment_status',
    'amount_due',
    'created_at',
    'items'
  ]) {
    test('missing required OrderOut field $field fails without a fallback', () {
      final json = orderJson()..remove(field);
      expect(() => Order.fromJson(json), throwsA(isA<AppFailure>()));
    });
  }

  for (final field in [
    'quantity',
    'unit_price',
    'gst_rate',
    'line_subtotal',
    'line_tax',
    'line_total'
  ]) {
    test(
        'numeric item $field is rejected instead of converted to double or zero',
        () {
      final item = orderItemJson()..[field] = 1.25;
      expect(() => OrderItem.fromJson(item), throwsA(isA<AppFailure>()));
    });
  }

  test('list envelope decodes typed orders and validates server pagination',
      () {
    final page = Paginated<Order>.fromJson(
        pageJson([orderJson()], total: 51), Order.fromJson);
    expect(page.total, 51);
    expect(page.page, 1);
    expect(page.pageSize, 50);
    expect(page.items.single.orderNumber, 'ORD-A');
    expect(page.hasNext, isTrue);
  });

  test('history is a chronological array with stable ties and nullable fields',
      () {
    final history = OrderHistory.parseList([
      historyJson(
          id: orderBId,
          from: 'pending',
          to: 'reserved',
          at: '2026-11-12T04:00:00Z',
          note: 'Later'),
      historyJson(to: 'pending', note: 'First'),
      historyJson(id: userBId, to: 'future_review', note: 'Same timestamp'),
    ]);
    expect(history.map((entry) => entry.note),
        ['First', 'Same timestamp', 'Later']);
    expect(history.first.fromStatus, isNull);
    expect(history.first.actorId, isNull);
    expect(history[1].toStatus, 'future_review');
    expect(() => history.add(history.first), throwsUnsupportedError);
  });

  for (final input in <Object?>[
    null,
    {},
    {'items': <Object?>[]},
    [null],
    [historyJson()..remove('created_at')],
    [historyJson()..['actor_id'] = 'bad-id']
  ].indexed) {
    test(
        'malformed history ${input.$1 + 1} is rejected without an envelope guess',
        () {
      expect(
          () => OrderHistory.parseList(input.$2), throwsA(isA<AppFailure>()));
    });
  }

  test(
      'catalog reads only the authoritative customer price and declared currency',
      () {
    final product = Product.fromJson(
        {...productJson(), 'base_price': '1.00', 'resolved_price': '2.00'});
    expect(product.price.text, '41.80');
    expect(product.currencyCode, 'INR');
    expect(() => Product.fromJson({...productJson(), 'price': null}),
        throwsA(isA<AppFailure>()));
    expect(() => Product.fromJson({...productJson(), 'price': 123.45}),
        throwsA(isA<AppFailure>()));
  });

  for (final patch in <Map<String, Object?>>[
    {'price': '-1.00'},
    {'price': '1.001'},
    {'price': '1e2'},
    {'price': '1000000000000.00'},
    {'gst_rate': '100.01'},
    {'gst_rate': '-1.00'},
    {'currency_code': 'usd'},
    {'currency_code': null},
  ].indexed) {
    test('invalid customer catalog field ${patch.$1 + 1} fails closed', () {
      expect(() => Product.fromJson({...productJson(), ...patch.$2}),
          throwsA(isA<AppFailure>()));
    });
  }

  test('zero prices and a non-INR currency remain exact server values', () {
    final product = Product.fromJson(
        {...productJson(), 'price': '0.00', 'currency_code': 'USD'});
    expect(product.price.text, '0.00');
    expect(product.currencyCode, 'USD');
  });
}
