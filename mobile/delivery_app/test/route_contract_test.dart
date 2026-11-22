import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_delivery/features/route/delivery_stop.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import 'support/delivery_fixtures.dart';

void main() {
  test(
      'assigned route consumes a bare typed array and preserves server priority order',
      () {
    final stops = DeliveryStop.parseList([
      stopJson(priority: 1),
      stopJson(orderId: orderBId, priority: 3, otp: true),
    ]);
    expect(stops.map((stop) => stop.priority), [1, 3]);
    expect(stops.first.orderId, orderAId);
    expect(stops.last.isOtpVerified, isTrue);
    expect(() => stops.clear(), throwsUnsupportedError);
  });

  for (final input in <Object?>[
    null,
    {},
    {'items': <Object?>[]},
    [null],
    [stopJson()..remove('id')],
    [stopJson()..['order_id'] = 'tiny'],
    [stopJson()..['priority'] = '1'],
    [stopJson()..['priority'] = -1],
    [stopJson()..['otp_verified'] = 'yes']
  ].indexed) {
    test(
        'malformed route ${input.$1 + 1} is rejected, not rendered as a fake stop',
        () {
      expect(
          () => DeliveryStop.parseList(input.$2), throwsA(isA<AppFailure>()));
    });
  }

  test(
      'short identifiers have safe presentation guards without substring crashes',
      () {
    expect(shortId('x'), 'x');
    expect(shortId(''), '');
    expect(shortId(orderAId), '55555555');
  });
}
