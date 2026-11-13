import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_delivery/features/auth/auth_provider.dart';

import '../../../packages/supplyos_core/test/support/offline_http.dart';

Map<String, Object?> stopJson(
        {String orderId = orderAId, int priority = 1, bool otp = false}) =>
    {
      'id': '77777777-7777-4777-8777-777777777777',
      'order_id': orderId,
      'priority': priority,
      'otp_verified': otp,
    };

class DeliveryHarness {
  DeliveryHarness(
      Future<OfflineResponse> Function(OfflineRequest request) read) {
    backend = OfflineBackend((request) {
      if (request.path == '/auth/login') {
        final isB = JsonObject(request.body).string('email').startsWith('b@');
        final id = isB ? userBId : userAId;
        return OfflineResponse({
          'user': userJson(
              id: id,
              tenantId: isB ? tenantBId : tenantAId,
              role: 'delivery_partner')
        }, cookies: sessionCookies(id));
      }
      if (request.path == '/auth/logout') return const OfflineResponse({});
      return read(request);
    });
    session = fixtureSession(backend, role: 'delivery_partner');
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
