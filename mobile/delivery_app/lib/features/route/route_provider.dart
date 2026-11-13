import 'package:supplyos_core/supplyos_core.dart';

import '../auth/auth_provider.dart';
import 'delivery_stop.dart';

final routeQuery = SessionQuery<List<DeliveryStop>, Object?>(
  sessionProvider: authProvider,
  load: (session, scope, argument, token) async => DeliveryStop.parseList(
    await session.get('/deliveries/my-route', scope: scope, cancelToken: token),
  ),
);

final routeProvider = routeQuery.provider;
