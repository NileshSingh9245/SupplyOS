import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/formatters.dart';
import '../auth/auth_provider.dart';
import 'order.dart';
import 'orders_provider.dart';

class OrderDetailScreen extends ConsumerWidget {
  const OrderDetailScreen({required this.id, super.key});

  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(authProvider.select((state) => state.key)) == null) {
      return const SizedBox.shrink();
    }
    final order = ref.watch(orderQuery.provider(id));
    final history = ref.watch(orderHistoryQuery.provider(id));
    Future<void> refresh() async {
      await Future.wait([
        ref.read(orderQuery.refreshProvider(id))(),
        ref.read(orderHistoryQuery.refreshProvider(id))(),
      ]);
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Order details'),
        leading: IconButton(
          tooltip: 'Back to orders',
          onPressed: () => context.go('/orders'),
          icon: const Icon(Icons.arrow_back),
        ),
        actions: [
          IconButton(
              tooltip: 'Refresh order',
              onPressed: refresh,
              icon: const Icon(Icons.refresh)),
          SessionLogoutButton(sessionProvider: authProvider),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: order.when(
          skipLoadingOnRefresh: false,
          skipLoadingOnReload: false,
          data: (value) => ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(20),
            children: [
              Text(value.orderNumber,
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Text(statusLabel(value.status)),
              const SizedBox(height: 20),
              _Field('Order ID', value.id),
              _Field('Channel', value.channel),
              _Field('Payment mode', value.paymentMode),
              _Field('Payment status', statusLabel(value.paymentStatus)),
              _Field('Subtotal', formatINR(value.subtotal)),
              _Field('Tax total', formatINR(value.taxTotal)),
              _Field('Discount total', formatINR(value.discountTotal)),
              _Field('Grand total', formatINR(value.grandTotal)),
              _Field('Amount paid', formatINR(value.amountPaid)),
              _Field('Amount due', formatINR(value.amountDue)),
              _Field('Credit hold', formatINR(value.creditHoldAmount)),
              _Field('Scheduled delivery',
                  formatDate(value.scheduledDeliveryDate)),
              _Field(
                  'Delivery address', value.deliveryAddress ?? 'Not provided'),
              _Field('Notes', value.notes ?? 'Not provided'),
              _Field('Created (server time)', formatDateTime(value.createdAt)),
              _Field(
                  'Confirmed (server time)', formatDateTime(value.confirmedAt)),
              _Field(
                  'Delivered (server time)', formatDateTime(value.deliveredAt)),
              const Divider(height: 32),
              Text('Items', style: Theme.of(context).textTheme.titleLarge),
              if (value.items.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Text('No items in the server response.'),
                ),
              for (final item in value.items) _OrderItemView(item),
              const Divider(height: 32),
              Text('History / oldest first',
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 12),
              history.when(
                skipLoadingOnRefresh: false,
                skipLoadingOnReload: false,
                data: (events) => events.isEmpty
                    ? const Text('No history recorded.')
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                            for (final event in events)
                              Padding(
                                padding: const EdgeInsets.only(bottom: 20),
                                child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(event.fromStatus == null
                                          ? statusLabel(event.toStatus)
                                          : '${statusLabel(event.fromStatus!)} -> ${statusLabel(event.toStatus)}'),
                                      Text(formatDateTime(event.createdAt)),
                                      if (event.note != null) Text(event.note!),
                                    ]),
                              ),
                          ]),
                loading: () => const LinearProgressIndicator(
                    semanticsLabel: 'Loading history'),
                error: (error, stack) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Unable to load history.'),
                    Text(AppFailure.safe(error).message),
                    OutlinedButton(
                      onPressed:
                          ref.read(orderHistoryQuery.refreshProvider(id)),
                      child: const Text('Retry history'),
                    ),
                  ],
                ),
              ),
            ],
          ),
          loading: () => const ReadLoading(),
          error: (error, stack) => ReadFeedback(
            title: 'Unable to load order.',
            message: AppFailure.safe(error).message,
            onRetry: refresh,
          ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.labelMedium),
          Text(value, style: Theme.of(context).textTheme.bodyLarge),
        ]),
      );
}

class _OrderItemView extends StatelessWidget {
  const _OrderItemView(this.item);

  final OrderItem item;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(item.productName,
              style: Theme.of(context).textTheme.titleMedium),
          Text('SKU: ${item.productSku}'),
          Text('Quantity: ${item.quantity}'),
          Text('Unit price: ${formatINR(item.unitPrice)}'),
          Text('GST rate: ${item.gstRate}'),
          Text('Line subtotal: ${formatINR(item.lineSubtotal)}'),
          Text('Line tax: ${formatINR(item.lineTax)}'),
          Text('Line total: ${formatINR(item.lineTotal)}'),
        ]),
      );
}
