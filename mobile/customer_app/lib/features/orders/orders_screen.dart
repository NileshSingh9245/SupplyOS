import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/formatters.dart';
import '../../core/customer_widgets.dart';
import '../auth/auth_provider.dart';
import 'orders_provider.dart';

class OrdersScreen extends ConsumerWidget {
  const OrdersScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scope = ref.watch(authProvider.select((state) => state.key));
    if (scope == null) return const SizedBox.shrink();
    final page = ref.watch(ordersPageProvider(scope));
    final filter = ref.watch(orderFilterProvider(scope));
    final unfiltered = filter.search.isEmpty && filter.status == null;
    final async = unfiltered
        ? ref.watch(ordersProvider(page))
        : ref.watch(filteredOrdersQuery.provider((filter, page)));
    final refresh = unfiltered
        ? ref.read(ordersQuery.refreshProvider(page))
        : ref.read(filteredOrdersQuery.refreshProvider((filter, page)));
    final data = async.asData?.value;
    void setFilter(OrderFilter value) {
      ref.read(ordersPageProvider(scope).notifier).state = 1;
      ref.read(orderFilterProvider(scope).notifier).state = value;
    }

    return Scaffold(
      appBar: AppBar(title: const Text('My orders'), actions: [
        IconButton(
            tooltip: 'Refresh orders',
            onPressed: async.isLoading ? null : refresh,
            icon: const Icon(Icons.refresh)),
        SessionLogoutButton(sessionProvider: authProvider),
      ]),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: CustomerList(children: [
          CustomerSearch(
            key: ValueKey(scope),
            label: 'Search order number',
            initialText: filter.search,
            onSearch: (text) =>
                setFilter(OrderFilter(search: text, status: filter.status)),
          ),
          const SizedBox(height: 12),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: const Text('All orders'),
                  selected: filter.status == null,
                  onSelected: (_) =>
                      setFilter(OrderFilter(search: filter.search)),
                ),
              ),
              for (final status in orderFilterStatuses)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(statusLabel(status)),
                    selected: filter.status == status,
                    onSelected: (_) => setFilter(
                        OrderFilter(search: filter.search, status: status)),
                  ),
                ),
            ]),
          ),
          const SizedBox(height: 20),
          async.when(
            skipLoadingOnRefresh: false,
            skipLoadingOnReload: false,
            data: (orders) => orders.items.isEmpty
                ? const InlineReadState(title: 'No orders on this page.')
                : Column(children: [
                    for (final order in orders.items)
                      Material(
                        color: Colors.transparent,
                        child: InkWell(
                          onTap: () => context.go('/orders/${order.id}'),
                          child: CustomerSection(
                            title: order.orderNumber,
                            child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(statusLabel(order.status)),
                                  Text(formatDateTime(order.createdAt)),
                                  const SizedBox(height: 8),
                                  Text(
                                      formatMoney(
                                          order.grandTotal, order.currencyCode),
                                      style: const TextStyle(
                                          fontWeight: FontWeight.w800)),
                                  const SizedBox(height: 12),
                                  const Text('View order and history'),
                                ]),
                          ),
                        ),
                      ),
                  ]),
            loading: () => const SizedBox(height: 220, child: ReadLoading()),
            error: (error, stack) => InlineReadState(
              title: 'Unable to load orders.',
              error: error,
              onRetry: refresh,
            ),
          ),
          if (data != null)
            PageControls(
              page: data.page,
              total: data.total,
              onPrevious: data.hasPrevious
                  ? () => ref.read(ordersPageProvider(scope).notifier).state =
                      page - 1
                  : null,
              onNext: data.hasNext
                  ? () => ref.read(ordersPageProvider(scope).notifier).state =
                      page + 1
                  : null,
            ),
        ]),
      ),
    );
  }
}
