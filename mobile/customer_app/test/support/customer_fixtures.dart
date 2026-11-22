import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_customer/features/auth/auth_provider.dart';

import '../../../packages/supplyos_core/test/support/offline_http.dart';

Map<String, Object?> orderItemJson() => {
      'id': '77777777-7777-4777-8777-777777777777',
      'product_id': '88888888-8888-4888-8888-888888888888',
      'product_sku': 'SKU-FIXTURE',
      'product_name': 'Fixture supply',
      'quantity': '2.000',
      'unit_price': '123.4500',
      'gst_rate': '18.000',
      'line_subtotal': '246.9000',
      'line_tax': '44.4420',
      'line_total': '291.3420',
    };

Map<String, Object?> orderJson(
        {String id = orderAId, String number = 'ORD-A'}) =>
    {
      'id': id,
      'order_number': number,
      'customer_id': userAId,
      'warehouse_id': tenantAId,
      'status': 'reserved',
      'channel': 'app',
      'subtotal': '246.9000',
      'tax_total': '44.4420',
      'discount_total': '1.2300',
      'grand_total': '1234567890123.4567890',
      'amount_paid': '10.0010',
      'payment_mode': 'credit',
      'credit_hold_amount': '200.0000',
      'payment_status': 'partially_paid',
      'amount_due': '281.3410',
      'scheduled_delivery_date': '2026-11-12',
      'delivery_address': 'Fixture address\nFixture city',
      'notes': 'Server note',
      'created_at': '2026-11-12T03:00:00Z',
      'confirmed_at': null,
      'delivered_at': null,
      'items': [orderItemJson()],
    };

Map<String, Object?> productJson({String name = 'Fixture product'}) => {
      'id': orderAId,
      'sku': 'SKU-BASE',
      'name': name,
      'unit': 'kg',
      'price': '41.80',
      'gst_rate': '18.00',
      'currency_code': 'INR',
    };

Map<String, Object?> pageJson(List<Object?> items,
        {int page = 1, int? total}) =>
    {
      'items': items,
      'total': total ?? items.length,
      'page': page,
      'page_size': 50,
    };

Map<String, Object?> historyJson({
  String id = orderAId,
  String? from,
  String to = 'pending',
  String at = '2026-11-12T03:00:00Z',
  String? note,
}) =>
    {
      'id': id,
      'from_status': from,
      'to_status': to,
      'actor_id': null,
      'note': note,
      'created_at': at,
    };

class CustomerHarness {
  CustomerHarness(
      Future<OfflineResponse> Function(OfflineRequest request) read) {
    backend = OfflineBackend((request) {
      if (request.path == '/auth/login') {
        final body = JsonObject(request.body);
        final isB = body.string('email').startsWith('b@');
        final id = isB ? userBId : userAId;
        return OfflineResponse(
            {'user': userJson(id: id, tenantId: isB ? tenantBId : tenantAId)},
            cookies: sessionCookies(id));
      }
      if (request.path == '/auth/logout') return const OfflineResponse({});
      return read(request);
    });
    session = fixtureSession(backend);
    container = ProviderContainer(
        overrides: [authProvider.overrideWith((ref) => session)]);
  }

  late final OfflineBackend backend;
  late final SessionController session;
  late final ProviderContainer container;

  Future<void> login({bool accountB = false}) => session.login(
      accountB ? 'b@offline.test' : 'a@offline.test', 'fixture-password');

  void dispose() => container.dispose();
}
