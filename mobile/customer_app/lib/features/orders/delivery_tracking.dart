import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';
import '../auth/auth_provider.dart';

class DeliveryTracking {
  const DeliveryTracking._({
    required this.id,
    required this.orderId,
    required this.priority,
    required this.otpVerified,
    required this.cashCollected,
    required this.upiCollected,
    required this.createdAt,
    this.partnerId,
    this.scheduledDate,
    this.signatureReference,
    this.photoReference,
    this.startedAt,
    this.completedAt,
  });

  final String id;
  final String orderId;
  final String? partnerId;
  final int priority;
  final bool otpVerified;
  final ServerDecimal cashCollected;
  final ServerDecimal upiCollected;
  final ServerTimestamp createdAt;
  final ServerDate? scheduledDate;
  final String? signatureReference;
  final String? photoReference;
  final ServerTimestamp? startedAt;
  final ServerTimestamp? completedAt;

  factory DeliveryTracking.fromJson(Object? input) {
    final json = JsonObject(input);
    return DeliveryTracking._(
      id: json.uuid('id'),
      orderId: json.uuid('order_id'),
      partnerId: json.optionalUuid('partner_id'),
      priority: json.integer('priority', minimum: 1, maximum: 10),
      otpVerified: json.boolean('otp_verified'),
      cashCollected: serverAmount(json.value('cash_collected')),
      upiCollected: serverAmount(json.value('upi_collected')),
      createdAt: json.timestamp('created_at'),
      scheduledDate: json.optionalDate('scheduled_date'),
      signatureReference: json.optionalString('signature_url'),
      photoReference: json.optionalString('proof_photo_url'),
      startedAt: json.optionalTimestamp('started_at'),
      completedAt: json.optionalTimestamp('completed_at'),
    );
  }
}

final deliveryTrackingQuery = SessionQuery<List<DeliveryTracking>, String>(
  sessionProvider: authProvider,
  load: (session, scope, orderId, token) async {
    if (!isUuid(orderId)) throw invalidResponse;
    final rows = serverList(
        await session.get('/deliveries', scope: scope, cancelToken: token),
        DeliveryTracking.fromJson);
    requireUniqueIds(rows, (row) => row.id);
    return List.unmodifiable(rows
        .where((row) => row.orderId.toLowerCase() == orderId.toLowerCase()));
  },
);
