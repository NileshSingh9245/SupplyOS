import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_customer/core/customer_contract.dart';
import 'package:supplyos_customer/core/formatters.dart';
import 'package:supplyos_customer/features/account/account.dart';
import 'package:supplyos_customer/features/catalog/catalog_provider.dart';
import 'package:supplyos_customer/features/catalog/product.dart';
import 'package:supplyos_customer/features/ordering/order_quote.dart';
import 'package:supplyos_customer/features/orders/delivery_tracking.dart';
import 'package:supplyos_customer/features/orders/order.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import 'support/customer_fixtures.dart';
import 'support/workflow_fixtures.dart';

const scope = SessionKey(userAId, tenantAId, 'customer', 1);

MutationRequest<OrderQuote> quoteRequest({String mode = 'cash'}) =>
    orderQuoteEndpoint.createRequest(
      QuoteInput(warehouseId: warehouseId, paymentMode: mode, items: [
        CartLine(
            product: Product.fromJson(workflowProduct()), quantity: '1.250'),
      ]),
      scope: scope,
      idempotencyKey: quoteId,
    );

AcceptedQuote acceptedFixture() {
  final request = quoteRequest();
  return AcceptedQuote(
      quote: OrderQuote.decode(quoteJson(body: request.body), request),
      original: request,
      customerId: customerAId);
}

void main() {
  test(
      'quote wire body carries exact quantities and no client financial or account authority',
      () {
    final request = quoteRequest();
    expect(request.path, '/order-quotes');
    expect(request.expectedStatus, 201);
    expect(request.idempotencyKey, quoteId);
    expect(request.body!.keys, ['warehouse_id', 'payment_mode', 'items']);
    expect(
        JsonObject(request.body)
            .list('items', JsonObject.new)
            .single
            .string('quantity'),
        '1.250');
    expect(() => request.body!['warehouse_id'] = inactiveWarehouseId,
        throwsUnsupportedError);
    expect(
        () => (request.body!['items'] as List).clear(), throwsUnsupportedError);
  });

  for (final value in [
    '',
    '0',
    '0.000',
    '-1',
    '+1',
    '1e2',
    ' 1.250',
    '1.250 ',
    '1.0001',
    '.5',
    '01',
    '10000000000000',
    'NaN',
    'Infinity'
  ]) {
    test('cart refuses unsupported quantity spelling $value', () {
      expect(isQuantityText(value), isFalse);
      expect(
          () => CartLine(
              product: Product.fromJson(workflowProduct()), quantity: value),
          throwsA(isA<AppFailure>()));
    });
  }

  for (final value in ['1', '1.250', '0.001', '9999999999999.999']) {
    test('cart preserves valid quantity spelling $value', () {
      final line = CartLine(
          product: Product.fromJson(workflowProduct()), quantity: value);
      expect(line.quantity, value);
      expect(line.toJson()['quantity'], value);
    });
  }

  test('quote exact server fields and both blockers are not recalculated', () {
    final request = quoteRequest(mode: 'credit');
    final quote = OrderQuote.decode(
        quoteJson(
            body: request.body,
            blockers: ['insufficient_stock', 'credit_limit_exceeded']),
        request);
    expect(quote.items.single.quantity.text, '1.250');
    expect(quote.items.single.unitPrice.text, '41.80');
    expect(quote.items.single.gstRate.text, '5.00');
    expect(quote.items.single.subtotal.text, '52.25');
    expect(quote.items.single.tax.text, '2.61');
    expect(quote.items.single.total.text, '54.86');
    expect(quote.subtotal.text, '52.25');
    expect(quote.taxTotal.text, '2.61');
    expect(quote.grandTotal.text, '54.86');
    expect(quote.currencyCode, 'USD');
    expect(quote.availability.single.availableQuantity.text, '0.000');
    expect(quote.blockers, ['insufficient_stock', 'credit_limit_exceeded']);
    expect(() => quote.items.clear(), throwsUnsupportedError);
    expect(() => quote.blockers.clear(), throwsUnsupportedError);
  });

  test('decimal spelling equality only binds values and preserves display text',
      () {
    final original = quoteRequest();
    final data = quoteJson(body: original.body);
    final item = Map<String, Object?>.from(
        (data['items'] as List).single as Map<String, Object?>);
    item['quantity'] = '1.25';
    data['items'] = [item];
    final result = OrderQuote.decode(data, original);
    expect(result.items.single.quantity.text, '1.25');
    expect(sameDecimalText('1.250', '1.25'), isTrue);
    expect(sameDecimalText('1.250', '1.251'), isFalse);
  });

  final invalidQuotes = <Map<String, Object?>>[
    {'id': orderBId},
    {'warehouse_id': inactiveWarehouseId},
    {'payment_mode': 'credit'},
    {'quote_proof': 'one.two.three'},
    {'quote_proof': 'https://not-a-proof.test'},
    {'currency_code': 'usd'},
    {'currency_code': null},
    {'expires_at': 'tomorrow'},
    {'subtotal': 52.25},
    {'tax_total': '-2.61'},
    {'grand_total': '5.486e1'},
    {'items': <Object?>[]},
    {'availability': <Object?>[]},
    {
      'blockers': ['unknown_server_blocker']
    },
    {
      'blockers': ['insufficient_stock', 'insufficient_stock']
    },
    {
      'blockers': ['credit_limit_exceeded']
    },
  ];
  for (final entry in invalidQuotes.indexed) {
    test('quote binding or format violation ${entry.$1} is denied', () {
      final original = quoteRequest();
      expect(
          () => OrderQuote.decode(
              {...quoteJson(body: original.body), ...entry.$2}, original),
          throwsA(isA<AppFailure>()));
    });
  }

  for (final field in [
    'id',
    'warehouse_id',
    'quote_proof',
    'expires_at',
    'currency_code',
    'payment_mode',
    'items',
    'availability',
    'blockers',
    'subtotal',
    'tax_total',
    'grand_total'
  ]) {
    test('quote requires server field $field', () {
      final original = quoteRequest();
      final input = quoteJson(body: original.body)..remove(field);
      expect(
          () => OrderQuote.decode(input, original), throwsA(isA<AppFailure>()));
    });
  }

  for (final field in ['product_id', 'quantity', 'gst_rate', 'unit_price']) {
    test('quote item binds and validates $field', () {
      final original = quoteRequest();
      final data = quoteJson(body: original.body);
      final item = Map<String, Object?>.from(
          (data['items'] as List).single as Map<String, Object?>);
      item[field] = field == 'product_id'
          ? productBId
          : field == 'quantity'
              ? '2.000'
              : field == 'gst_rate'
                  ? '100.01'
                  : 41.80;
      data['items'] = [item];
      expect(
          () => OrderQuote.decode(data, original), throwsA(isA<AppFailure>()));
    });
  }

  test('quote availability required quantity and product identities are bound',
      () {
    final original = quoteRequest();
    for (final patch in [
      {'product_id': productBId},
      {'required_quantity': '2.000'},
      {'available_quantity': -1},
    ]) {
      final data = quoteJson(body: original.body);
      data['availability'] = [
        {
          ...(data['availability'] as List).single as Map<String, Object?>,
          ...patch
        }
      ];
      expect(
          () => OrderQuote.decode(data, original), throwsA(isA<AppFailure>()));
    }
  });

  test(
      'quote decoder rejects a wrong success status instead of publishing a receipt',
      () async {
    final original = quoteRequest();
    await expectLater(
        original.decodeResponse(200, quoteJson(body: original.body)),
        throwsA(isA<AppFailure>()
            .having((error) => error.isOutcomeUncertain, 'uncertain', isTrue)));
  });

  test(
      'atomic checkout wire body is ONLY quote identity and proof with matching key',
      () async {
    final accepted = acceptedFixture();
    final request = checkoutEndpoint(accepted).createRequest(accepted,
        scope: scope, idempotencyKey: accepted.quote.id);
    expect(request.expectedStatus, 201);
    expect(request.body,
        {'quote_id': quoteId, 'quote_proof': accepted.quote.proof});
    final data = checkoutJson(
        quoteJson(body: accepted.original.body), accepted.original.body!);
    final response = await request.decodeResponse(201, data);
    expect(response.value.order.status, 'reserved');
    expect(response.value.order.currencyCode, 'USD');
    expect(response.value.order.grandTotal.text, '54.86');
    expect(response.value.order.items.single.quantity.text, '1.250');
    expect(response.value.quoteId, quoteId);
  });

  for (final patch in <Map<String, Object?>>[
    {'quote_id': orderBId},
    {'customer_id': customerBId},
    {'warehouse_id': inactiveWarehouseId},
    {'currency_code': 'EUR'},
    {'currency_code': null},
    {'payment_mode': 'credit'},
    {'status': 'pending'},
    {'channel': 'web'},
    {'subtotal': '52.26'},
    {'tax_total': '2.62'},
    {'grand_total': '54.87'},
    {'items': <Object?>[]},
    {'delivery_address': 'Another address'},
    {'notes': 'Another instruction'},
  ].indexed) {
    test('checkout denies a mismatched original receipt ${patch.$1}', () async {
      final accepted = acceptedFixture();
      final request = checkoutEndpoint(accepted)
          .createRequest(accepted, scope: scope, idempotencyKey: quoteId);
      final data = {
        ...checkoutJson(
            quoteJson(body: accepted.original.body), accepted.original.body!),
        ...patch.$2
      };
      expect(() => CheckoutReceipt.decode(data, request, accepted),
          throwsA(isA<AppFailure>()));
    });
  }

  test(
      'checkout rejects wrong original scope or key and cannot encode a different acceptance',
      () {
    final accepted = acceptedFixture();
    final endpoint = checkoutEndpoint(accepted);
    final data = checkoutJson(
        quoteJson(body: accepted.original.body), accepted.original.body!);
    for (final request in [
      endpoint.createRequest(accepted, scope: scope, idempotencyKey: orderBId),
      endpoint.createRequest(accepted,
          scope: const SessionKey(userBId, tenantBId, 'customer', 2),
          idempotencyKey: quoteId),
    ]) {
      expect(() => CheckoutReceipt.decode(data, request, accepted),
          throwsA(isA<AppFailure>()));
    }
    expect(
        () => endpoint.createRequest(acceptedFixture(),
            scope: scope, idempotencyKey: quoteId),
        throwsA(isA<AppFailure>()));
  });

  test(
      'legacy order currency stays unknown instead of adopting a current catalog currency',
      () {
    final legacy = Order.fromJson(orderJson()..remove('currency_code'));
    expect(legacy.currencyCode, isNull);
    expect(formatMoney(legacy.grandTotal, legacy.currencyCode),
        '1234567890123.4567890 (currency not recorded)');
    expect(() => Order.fromJson({...orderJson(), 'currency_code': 'usd'}),
        throwsA(isA<AppFailure>()));
  });

  test('product detail uses the effective catalog price and optional metadata',
      () {
    final detail =
        ProductDetail.fromJson({...workflowDetail(), 'base_price': '999.00'});
    expect(detail.product.price.text, '41.80');
    expect(detail.product.currencyCode, 'USD');
    expect(detail.description, contains('server supplied'));
    expect(detail.imageUrl, isNull);
    expect(detail.product.categoryId, categoryId);
    expect(() => ProductDetail.fromJson(workflowDetail()..remove('price')),
        throwsA(isA<AppFailure>()));
  });

  test('catalog query filters are typed and never send account authority', () {
    expect(
        const CatalogFilter(page: 2, search: 'rice', categoryId: categoryId)
            .parameters,
        {'page': 2, 'page_size': 50, 'q': 'rice', 'category_id': categoryId});
    expect(() => const CatalogFilter(page: 0).parameters,
        throwsA(isA<AppFailure>()));
    expect(() => const CatalogFilter(categoryId: '../orders').parameters,
        throwsA(isA<AppFailure>()));
  });

  test(
      'own profile requires exactly one server-linked customer, never a first-row fallback',
      () {
    expect(CustomerProfile.parseOwn(pageJson([profileJson()])).id, customerAId);
    expect(() => CustomerProfile.parseOwn(pageJson([])),
        throwsA(isA<AppFailure>()));
    expect(
        () => CustomerProfile.parseOwn(
            pageJson([profileJson(), profileJson(accountB: true)])),
        throwsA(isA<AppFailure>()));
    final profile =
        CustomerProfile.fromJson({...profileJson(), 'currency_code': 'USD'});
    expect(formatMoney(profile.advanceBalance, null),
        '7.0100 (currency not recorded)');
  });

  test(
      'ledger, receipts and delivery projections retain their actual contracts',
      () {
    expect(LedgerEntry.fromJson(ledgerJson()).balanceAfter.text, '-7.0100');
    final receipt = PaymentReceipt.fromJson(paymentJson());
    expect(receipt.customerId, customerAId);
    expect(receipt.amount.text, '37.2500');
    expect(
        formatMoney(receipt.amount, null), '37.2500 (currency not recorded)');
    final tracking = DeliveryTracking.fromJson(deliveryJson());
    expect(tracking.orderId, orderAId);
    expect(tracking.otpVerified, isFalse);
    expect(tracking.completedAt, isNull);
    expect(() => PaymentReceipt.fromJson({...paymentJson(), 'amount': 37.25}),
        throwsA(isA<AppFailure>()));
    expect(
        () => DeliveryTracking.fromJson(
            {...deliveryJson(), 'order_id': 'not-an-id'}),
        throwsA(isA<AppFailure>()));
  });

  test(
      'stock observations preserve signed or aggregate server quantity without deriving eligibility',
      () {
    final original = quoteRequest();
    for (final available in ['-1.000', '25000000000000.000']) {
      final data =
          quoteJson(body: original.body, blockers: ['insufficient_stock']);
      data['availability'] = [
        {
          'product_id': productAId,
          'required_quantity': '1.250',
          'available_quantity': available,
        }
      ];
      final quote = OrderQuote.decode(data, original);
      expect(quote.availability.single.availableQuantity.text, available);
      expect(quote.blockers, ['insufficient_stock']);
    }
  });
}
