import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../auth/auth_provider.dart';
import 'order.dart';

const ordersPageSize = 50;

final ordersPageProvider =
    StateProvider.autoDispose.family<int, SessionKey>((ref, scope) => 1);

final ordersQuery = SessionQuery<Paginated<Order>, int>(
  sessionProvider: authProvider,
  load: (session, scope, page, token) async {
    if (page < 1) throw invalidResponse;
    final data = await session.get(
      '/orders',
      scope: scope,
      queryParameters: {'page': page, 'page_size': ordersPageSize},
      cancelToken: token,
    );
    final result = Paginated<Order>.fromJson(data, Order.fromJson);
    result.requirePage(page, ordersPageSize);
    return result;
  },
);

final ordersProvider = ordersQuery.provider;

final orderQuery = SessionQuery<Order, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) async {
    if (!isUuid(id)) throw invalidResponse;
    final order = Order.fromJson(await session.get(
      '/orders/${id.toLowerCase()}',
      scope: scope,
      cancelToken: token,
    ));
    if (order.id.toLowerCase() != id.toLowerCase()) throw invalidResponse;
    return order;
  },
);

final orderHistoryQuery = SessionQuery<List<OrderHistory>, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) async {
    if (!isUuid(id)) throw invalidResponse;
    return OrderHistory.parseList(await session.get(
      '/orders/${id.toLowerCase()}/history',
      scope: scope,
      cancelToken: token,
    ));
  },
);
