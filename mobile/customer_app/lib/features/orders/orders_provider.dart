import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';
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

const orderFilterStatuses = [
  'pending',
  'confirmed',
  'reserved',
  'picked',
  'packed',
  'out_for_delivery',
  'delivered',
  'paid',
  'completed',
  'cancelled',
];

class OrderFilter {
  const OrderFilter({this.search = '', this.status});
  final String search;
  final String? status;

  Map<String, Object?> parameters(int page) {
    if (page < 1 ||
        search.length > 200 ||
        (status != null && !orderFilterStatuses.contains(status))) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
    return {
      'page': page,
      'page_size': ordersPageSize,
      if (search.isNotEmpty) 'q': search,
      if (status != null) 'status': status,
    };
  }

  @override
  bool operator ==(Object other) =>
      other is OrderFilter && search == other.search && status == other.status;
  @override
  int get hashCode => Object.hash(search, status);
}

final orderFilterProvider = StateProvider.autoDispose
    .family<OrderFilter, SessionKey>((ref, scope) => const OrderFilter());

final filteredOrdersQuery = SessionQuery<Paginated<Order>, (OrderFilter, int)>(
  sessionProvider: authProvider,
  load: (session, scope, argument, token) async {
    final result = Paginated<Order>.fromJson(
        await session.get('/orders',
            scope: scope,
            queryParameters: argument.$1.parameters(argument.$2),
            cancelToken: token),
        Order.fromJson);
    result.requirePage(argument.$2, ordersPageSize);
    requireUniqueIds(result.items, (order) => order.id);
    if (argument.$1.status != null &&
        result.items.any((order) => order.status != argument.$1.status)) {
      throw invalidResponse;
    }
    return result;
  },
);

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
