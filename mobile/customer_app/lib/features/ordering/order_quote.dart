import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';
import '../catalog/product.dart';
import '../orders/order.dart';

class ActiveWarehouse {
  const ActiveWarehouse._({
    required this.id,
    required this.code,
    required this.name,
    required this.isActive,
    this.address,
    this.city,
  });

  final String id;
  final String code;
  final String name;
  final bool isActive;
  final String? address;
  final String? city;

  factory ActiveWarehouse.fromJson(Object? input) {
    final json = JsonObject(input);
    return ActiveWarehouse._(
      id: json.uuid('id'),
      code: serverText(json.value('code'), maxLength: 30),
      name: serverText(json.value('name'), maxLength: 200),
      isActive: json.boolean('is_active'),
      address: json.optionalString('address'),
      city: json.optionalString('city'),
    );
  }
}

class CartLine {
  CartLine({required this.product, required this.quantity}) {
    if (!isQuantityText(quantity)) {
      throw const AppFailure(FailureKind.validation);
    }
  }

  final Product product;
  final String quantity;
  String get productId => product.id.toLowerCase();

  Map<String, Object?> toJson() =>
      {'product_id': productId, 'quantity': quantity};
}

class QuoteInput {
  QuoteInput({
    required this.warehouseId,
    required this.paymentMode,
    required List<CartLine> items,
    this.deliveryAddress,
    this.scheduledDeliveryDate,
    this.notes,
  }) : items = List.unmodifiable(items);

  final String warehouseId;
  final String paymentMode;
  final List<CartLine> items;
  final String? deliveryAddress;
  final String? scheduledDeliveryDate;
  final String? notes;

  Map<String, Object?> toJson() {
    if (!isUuid(warehouseId) ||
        !const {'cash', 'credit'}.contains(paymentMode) ||
        items.isEmpty ||
        items.length > 200 ||
        items.map((line) => line.productId).toSet().length != items.length ||
        (deliveryAddress?.length ?? 0) > 500 ||
        (notes?.length ?? 0) > 500) {
      throw const AppFailure(FailureKind.validation);
    }
    if (scheduledDeliveryDate != null) {
      try {
        ServerDate.parse(scheduledDeliveryDate);
      } catch (_) {
        throw const AppFailure(FailureKind.validation);
      }
    }
    final address = deliveryAddress?.trim();
    final instructions = notes?.trim();
    return {
      'warehouse_id': warehouseId.toLowerCase(),
      'payment_mode': paymentMode,
      if (address != null && address.isNotEmpty) 'delivery_address': address,
      if (scheduledDeliveryDate != null)
        'scheduled_delivery_date': scheduledDeliveryDate,
      if (instructions != null && instructions.isNotEmpty)
        'notes': instructions,
      'items': [for (final line in items) line.toJson()],
    };
  }
}

class QuoteItem {
  const QuoteItem._({
    required this.productId,
    required this.sku,
    required this.name,
    required this.unit,
    required this.quantity,
    required this.unitPrice,
    required this.gstRate,
    required this.subtotal,
    required this.tax,
    required this.total,
  });

  final String productId;
  final String sku;
  final String name;
  final String unit;
  final ServerDecimal quantity;
  final ServerDecimal unitPrice;
  final ServerDecimal gstRate;
  final ServerDecimal subtotal;
  final ServerDecimal tax;
  final ServerDecimal total;

  factory QuoteItem.fromJson(Object? input) {
    final json = JsonObject(input);
    return QuoteItem._(
      productId: json.uuid('product_id'),
      sku: serverText(json.value('sku'), maxLength: 64),
      name: serverText(json.value('name'), maxLength: 255),
      unit: serverText(json.value('unit'), maxLength: 50),
      quantity: serverQuantity(json.value('quantity')),
      unitPrice: serverAmount(json.value('unit_price')),
      gstRate: serverTaxRate(json.value('gst_rate')),
      subtotal: serverAmount(json.value('subtotal')),
      tax: serverAmount(json.value('tax')),
      total: serverAmount(json.value('total')),
    );
  }
}

class StockAvailability {
  const StockAvailability._(
      this.productId, this.requiredQuantity, this.availableQuantity);

  final String productId;
  final ServerDecimal requiredQuantity;
  final ServerDecimal availableQuantity;

  factory StockAvailability.fromJson(Object? input) {
    final json = JsonObject(input);
    return StockAvailability._(
      json.uuid('product_id'),
      serverQuantity(json.value('required_quantity')),
      // Availability is a signed server observation, not a client stock check.
      serverAmount(json.value('available_quantity'), signed: true),
    );
  }
}

class OrderQuote {
  const OrderQuote._({
    required this.id,
    required this.proof,
    required this.warehouseId,
    required this.expiresAt,
    required this.currencyCode,
    required this.paymentMode,
    required this.items,
    required this.subtotal,
    required this.taxTotal,
    required this.grandTotal,
    required this.availability,
    required this.blockers,
  });

  final String id;
  final String proof;
  final String warehouseId;
  final ServerTimestamp expiresAt;
  final String currencyCode;
  final String paymentMode;
  final List<QuoteItem> items;
  final ServerDecimal subtotal;
  final ServerDecimal taxTotal;
  final ServerDecimal grandTotal;
  final List<StockAvailability> availability;
  final List<String> blockers;

  bool expiredAt(DateTime now) => !expiresAt.value.isAfter(now.toUtc());

  factory OrderQuote.decode(
      Object? input, MutationRequest<OrderQuote> original) {
    final json = JsonObject(input);
    final request = JsonObject(original.body);
    final id = json.uuid('id');
    final warehouse = json.uuid('warehouse_id');
    final proof = json.string('quote_proof');
    final mode = json.string('payment_mode');
    if (original.path != '/order-quotes' ||
        original.scope.role != 'customer' ||
        original.idempotencyKey != id.toLowerCase() ||
        warehouse.toLowerCase() != request.uuid('warehouse_id').toLowerCase() ||
        !const {'cash', 'credit'}.contains(mode) ||
        mode != request.string('payment_mode') ||
        proof.length > 32768 ||
        !RegExp(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$').hasMatch(proof)) {
      throw invalidResponse;
    }
    final items = json.list('items', QuoteItem.fromJson);
    final availability = json.list('availability', StockAvailability.fromJson);
    final requested = request.list('items', JsonObject.new);
    if (items.isEmpty ||
        items.length != requested.length ||
        availability.length != requested.length) {
      throw invalidResponse;
    }
    requireUniqueIds(items, (item) => item.productId);
    requireUniqueIds(availability, (item) => item.productId);
    final expected = {
      for (final item in requested)
        item.uuid('product_id').toLowerCase(): item.string('quantity'),
    };
    if (expected.length != requested.length) throw invalidResponse;
    for (final item in items) {
      final quantity = expected[item.productId.toLowerCase()];
      if (quantity == null || !sameDecimalText(quantity, item.quantity.text)) {
        throw invalidResponse;
      }
    }
    for (final observation in availability) {
      final quantity = expected[observation.productId.toLowerCase()];
      if (quantity == null ||
          !sameDecimalText(quantity, observation.requiredQuantity.text)) {
        throw invalidResponse;
      }
    }
    final blockers = json.list('blockers', (value) {
      if (value is! String ||
          !const {'insufficient_stock', 'credit_limit_exceeded'}
              .contains(value)) {
        throw invalidResponse;
      }
      return value;
    });
    if (blockers.toSet().length != blockers.length ||
        (mode == 'cash' && blockers.contains('credit_limit_exceeded'))) {
      throw invalidResponse;
    }
    return OrderQuote._(
      id: id,
      proof: proof,
      warehouseId: warehouse,
      expiresAt: json.timestamp('expires_at'),
      currencyCode: serverCurrency(json.value('currency_code')),
      paymentMode: mode,
      items: items,
      subtotal: serverAmount(json.value('subtotal')),
      taxTotal: serverAmount(json.value('tax_total')),
      grandTotal: serverAmount(json.value('grand_total')),
      availability: availability,
      blockers: blockers,
    );
  }
}

final orderQuoteEndpoint = JsonMutationEndpoint<QuoteInput, OrderQuote>(
  method: MutationMethod.post,
  path: '/order-quotes',
  expectedStatus: 201,
  supportsIdempotency: true,
  encode: (input) => input.toJson(),
  decode: OrderQuote.decode,
);

class AcceptedQuote {
  const AcceptedQuote({
    required this.quote,
    required this.original,
    required this.customerId,
  });

  final OrderQuote quote;
  final MutationRequest<OrderQuote> original;
  final String customerId;
}

class CheckoutReceipt {
  const CheckoutReceipt._(this.order, this.quoteId);

  final Order order;
  final String quoteId;

  factory CheckoutReceipt.decode(Object? input,
      MutationRequest<CheckoutReceipt> original, AcceptedQuote accepted) {
    final json = JsonObject(input);
    final request = JsonObject(original.body);
    final quote = accepted.quote;
    final intent = JsonObject(accepted.original.body);
    final order = Order.fromJson(input);
    final quoteId = json.uuid('quote_id');
    if (original.path != '/orders/checkout' ||
        original.scope != accepted.original.scope ||
        original.idempotencyKey != quote.id.toLowerCase() ||
        request.uuid('quote_id').toLowerCase() != quote.id.toLowerCase() ||
        quoteId.toLowerCase() != quote.id.toLowerCase() ||
        request.string('quote_proof') != quote.proof ||
        order.customerId.toLowerCase() != accepted.customerId.toLowerCase() ||
        order.warehouseId.toLowerCase() != quote.warehouseId.toLowerCase() ||
        order.currencyCode != quote.currencyCode ||
        order.paymentMode != quote.paymentMode ||
        order.status != 'reserved' ||
        order.channel != 'app' ||
        order.scheduledDeliveryDate?.text !=
            intent.optionalString('scheduled_delivery_date') ||
        order.deliveryAddress != intent.optionalString('delivery_address') ||
        order.notes != intent.optionalString('notes') ||
        !sameDecimalText(order.subtotal.text, quote.subtotal.text) ||
        !sameDecimalText(order.taxTotal.text, quote.taxTotal.text) ||
        !sameDecimalText(order.grandTotal.text, quote.grandTotal.text) ||
        order.items.length != quote.items.length) {
      throw invalidResponse;
    }
    requireUniqueIds(order.items, (item) => item.productId);
    requireUniqueIds(order.items, (item) => item.id);
    final quoted = {
      for (final item in quote.items) item.productId.toLowerCase(): item,
    };
    for (final item in order.items) {
      final expected = quoted[item.productId.toLowerCase()];
      if (expected == null ||
          item.productSku != expected.sku ||
          item.productName != expected.name ||
          !sameDecimalText(item.quantity.text, expected.quantity.text) ||
          !sameDecimalText(item.unitPrice.text, expected.unitPrice.text) ||
          !sameDecimalText(item.gstRate.text, expected.gstRate.text) ||
          !sameDecimalText(item.lineSubtotal.text, expected.subtotal.text) ||
          !sameDecimalText(item.lineTax.text, expected.tax.text) ||
          !sameDecimalText(item.lineTotal.text, expected.total.text)) {
        throw invalidResponse;
      }
    }
    return CheckoutReceipt._(order, quoteId);
  }
}

JsonMutationEndpoint<AcceptedQuote, CheckoutReceipt> checkoutEndpoint(
        AcceptedQuote accepted) =>
    JsonMutationEndpoint(
      method: MutationMethod.post,
      path: '/orders/checkout',
      expectedStatus: 201,
      supportsIdempotency: true,
      encode: (input) {
        if (!identical(input, accepted)) {
          throw const AppFailure(FailureKind.invalidRequest);
        }
        return {
          'quote_id': input.quote.id.toLowerCase(),
          'quote_proof': input.quote.proof,
        };
      },
      decode: (response, original) =>
          CheckoutReceipt.decode(response, original, accepted),
    );
