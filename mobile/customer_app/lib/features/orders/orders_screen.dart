import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/formatters.dart';
import '../auth/auth_provider.dart';
import 'orders_provider.dart';

class OrdersScreen extends ConsumerWidget {
  const OrdersScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scope = ref.watch(authProvider.select((state) => state.key));
    if (scope == null) return const SizedBox.shrink();
    final page = ref.watch(ordersPageProvider(scope));
    final async = ref.watch(ordersProvider(page));
    final refresh = ref.read(ordersQuery.refreshProvider(page));
    final data = async.asData?.value;
    return Scaffold(
      appBar: AppBar(title: const Text('My orders'), actions: [
        IconButton(
            tooltip: 'Refresh orders',
            onPressed: async.isLoading ? null : refresh,
            icon: const Icon(Icons.refresh)),
        SessionLogoutButton(sessionProvider: authProvider),
      ]),
      body: Column(children: [
        Expanded(
            child: RefreshIndicator(
          onRefresh: refresh,
          child: async.when(
            skipLoadingOnRefresh: false,
            skipLoadingOnReload: false,
            data: (orders) => orders.items.isEmpty
                ? const ReadFeedback(title: 'No orders on this page.')
                : ListView.separated(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(16),
                    itemCount: orders.items.length,
                    separatorBuilder: (_, index) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final order = orders.items[index];
                      return ListTile(
                        title: Text(order.orderNumber),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(statusLabel(order.status)),
                            Text(formatDateTime(order.createdAt)),
                            Text(formatINR(order.grandTotal),
                                style: const TextStyle(
                                    fontWeight: FontWeight.w800)),
                          ],
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => context.go('/orders/${order.id}'),
                      );
                    },
                  ),
            loading: () => const ReadLoading(),
            error: (error, stack) => ReadFeedback(
              title: 'Unable to load orders.',
              message: AppFailure.safe(error).message,
              onRetry: refresh,
            ),
          ),
        )),
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
    );
  }
}
