import 'package:supplyos_core/supplyos_core.dart';

class OrderItem {
  const OrderItem._({
    required this.id,
    required this.productId,
    required this.productSku,
    required this.productName,
    required this.quantity,
    required this.unitPrice,
    required this.gstRate,
    required this.lineSubtotal,
    required this.lineTax,
    required this.lineTotal,
  });

  final String id;
  final String productId;
  final String productSku;
  final String productName;
  final ServerDecimal quantity;
  final ServerDecimal unitPrice;
  final ServerDecimal gstRate;
  final ServerDecimal lineSubtotal;
  final ServerDecimal lineTax;
  final ServerDecimal lineTotal;

  factory OrderItem.fromJson(Object? input) {
    final json = JsonObject(input);
    return OrderItem._(
      id: json.uuid('id'),
      productId: json.uuid('product_id'),
      productSku: json.string('product_sku'),
      productName: json.string('product_name'),
      quantity: json.decimal('quantity'),
      unitPrice: json.decimal('unit_price'),
      gstRate: json.decimal('gst_rate'),
      lineSubtotal: json.decimal('line_subtotal'),
      lineTax: json.decimal('line_tax'),
      lineTotal: json.decimal('line_total'),
    );
  }
}

class Order {
  const Order._({
    required this.id,
    required this.orderNumber,
    required this.customerId,
    required this.warehouseId,
    required this.status,
    required this.channel,
    required this.subtotal,
    required this.taxTotal,
    required this.discountTotal,
    required this.grandTotal,
    required this.amountPaid,
    required this.paymentMode,
    required this.creditHoldAmount,
    required this.paymentStatus,
    required this.amountDue,
    required this.createdAt,
    required this.items,
    this.scheduledDeliveryDate,
    this.deliveryAddress,
    this.notes,
    this.confirmedAt,
    this.deliveredAt,
  });

  final String id;
  final String orderNumber;
  final String customerId;
  final String warehouseId;
  final String status;
  final String channel;
  final ServerDecimal subtotal;
  final ServerDecimal taxTotal;
  final ServerDecimal discountTotal;
  final ServerDecimal grandTotal;
  final ServerDecimal amountPaid;
  final String paymentMode;
  final ServerDecimal creditHoldAmount;
  final String paymentStatus;
  final ServerDecimal amountDue;
  final ServerDate? scheduledDeliveryDate;
  final String? deliveryAddress;
  final String? notes;
  final ServerTimestamp createdAt;
  final ServerTimestamp? confirmedAt;
  final ServerTimestamp? deliveredAt;
  final List<OrderItem> items;

  factory Order.fromJson(Object? input) {
    final json = JsonObject(input);
    return Order._(
      id: json.uuid('id'),
      orderNumber: json.string('order_number'),
      customerId: json.uuid('customer_id'),
      warehouseId: json.uuid('warehouse_id'),
      status: json.string('status'),
      channel: json.string('channel'),
      subtotal: json.decimal('subtotal'),
      taxTotal: json.decimal('tax_total'),
      discountTotal: json.decimal('discount_total'),
      grandTotal: json.decimal('grand_total'),
      amountPaid: json.decimal('amount_paid'),
      paymentMode: json.string('payment_mode'),
      creditHoldAmount: json.decimal('credit_hold_amount'),
      paymentStatus: json.string('payment_status'),
      amountDue: json.decimal('amount_due'),
      scheduledDeliveryDate: json.optionalDate('scheduled_delivery_date'),
      deliveryAddress: json.optionalString('delivery_address'),
      notes: json.optionalString('notes'),
      createdAt: json.timestamp('created_at'),
      confirmedAt: json.optionalTimestamp('confirmed_at'),
      deliveredAt: json.optionalTimestamp('delivered_at'),
      items: json.list('items', OrderItem.fromJson),
    );
  }
}

class OrderHistory {
  const OrderHistory._({
    required this.id,
    required this.toStatus,
    required this.createdAt,
    this.fromStatus,
    this.actorId,
    this.note,
  });

  final String id;
  final String? fromStatus;
  final String toStatus;
  final String? actorId;
  final String? note;
  final ServerTimestamp createdAt;

  factory OrderHistory.fromJson(Object? input) {
    final json = JsonObject(input);
    return OrderHistory._(
      id: json.uuid('id'),
      fromStatus: json.optionalString('from_status'),
      toStatus: json.string('to_status'),
      actorId: json.optionalUuid('actor_id'),
      note: json.optionalString('note'),
      createdAt: json.timestamp('created_at'),
    );
  }

  static List<OrderHistory> parseList(Object? input) {
    if (input is! List<Object?>) throw invalidResponse;
    final indexed = input.map(OrderHistory.fromJson).indexed.toList();
    indexed.sort((a, b) {
      final time = a.$2.createdAt.value.compareTo(b.$2.createdAt.value);
      return time == 0 ? a.$1.compareTo(b.$1) : time;
    });
    return List.unmodifiable(indexed.map((entry) => entry.$2));
  }
}
