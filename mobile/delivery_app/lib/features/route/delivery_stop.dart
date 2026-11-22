import 'package:supplyos_core/supplyos_core.dart';

class DeliveryStop {
  const DeliveryStop._({
    required this.id,
    required this.orderId,
    required this.priority,
    required this.isOtpVerified,
  });

  final String id;
  final String orderId;
  final int priority;
  final bool isOtpVerified;

  factory DeliveryStop.fromJson(Object? input) {
    final json = JsonObject(input);
    return DeliveryStop._(
      id: json.uuid('id'),
      orderId: json.uuid('order_id'),
      priority: json.integer('priority'),
      isOtpVerified: json.boolean('otp_verified'),
    );
  }

  static List<DeliveryStop> parseList(Object? input) {
    if (input is! List<Object?>) throw invalidResponse;
    return List.unmodifiable(input.map(DeliveryStop.fromJson));
  }
}
