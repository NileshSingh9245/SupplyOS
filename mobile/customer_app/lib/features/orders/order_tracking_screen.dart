import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_widgets.dart';
import '../../core/formatters.dart';
import '../auth/auth_provider.dart';
import 'delivery_tracking.dart';
import 'orders_provider.dart';

class OrderTrackingScreen extends ConsumerWidget {
  const OrderTrackingScreen({required this.id, super.key});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scope = ref.watch(authProvider.select((value) => value.key));
    if (scope == null) {
      return const SizedBox.shrink();
    }
    final order = ref.watch(orderQuery.provider(id));
    final tracking = order.asData == null
        ? null
        : ref.watch(deliveryTrackingQuery.provider(id));
    Future<void> refresh() async {
      await ref.read(orderQuery.refreshProvider(id))();
      if (ref.read(authProvider).key == scope) {
        await ref.read(deliveryTrackingQuery.refreshProvider(id))();
      }
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Delivery tracking'),
        leading: IconButton(
            tooltip: 'Back to order',
            onPressed: () => context.go('/orders/$id'),
            icon: const Icon(Icons.arrow_back)),
        actions: [
          IconButton(
              tooltip: 'Refresh tracking',
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
          data: (value) => CustomerList(children: [
            CustomerSection(
              title: value.orderNumber,
              icon: Icons.local_shipping_outlined,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    DataField('Order status reported by server',
                        statusLabel(value.status)),
                    DataField('Requested delivery',
                        formatDate(value.scheduledDeliveryDate)),
                    DataField('Delivery address',
                        value.deliveryAddress ?? 'Not provided'),
                  ]),
            ),
            const CustomerNotice(
                'Online server updates only. Refresh to see the latest delivery records.'),
            if (tracking != null)
              tracking.when(
                skipLoadingOnRefresh: false,
                skipLoadingOnReload: false,
                data: (rows) => rows.isEmpty
                    ? const InlineReadState(title: 'No delivery record yet.')
                    : Column(children: [
                        for (final delivery in rows)
                          CustomerSection(
                              title: 'Delivery record',
                              child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    DataField('Delivery ID', delivery.id),
                                    DataField('Scheduled delivery',
                                        formatDate(delivery.scheduledDate)),
                                    DataField('Started (server time)',
                                        formatDateTime(delivery.startedAt)),
                                    DataField('Completed (server time)',
                                        formatDateTime(delivery.completedAt)),
                                    DataField(
                                        'Recipient verification',
                                        delivery.otpVerified
                                            ? 'Recorded by server'
                                            : 'Not recorded'),
                                    DataField(
                                        'Signature record',
                                        delivery.signatureReference == null
                                            ? 'Not recorded'
                                            : 'Recorded by server'),
                                    DataField(
                                        'Photo record',
                                        delivery.photoReference == null
                                            ? 'Not recorded'
                                            : 'Recorded by server'),
                                    DataField(
                                        'Cash collected',
                                        formatMoney(delivery.cashCollected,
                                            value.currencyCode)),
                                    DataField(
                                        'UPI collected',
                                        formatMoney(delivery.upiCollected,
                                            value.currencyCode)),
                                  ])),
                      ]),
                loading: () => const LinearProgressIndicator(
                    semanticsLabel: 'Loading delivery records'),
                error: (error, _) => InlineReadState(
                    title: 'Unable to load tracking.',
                    error: error,
                    onRetry:
                        ref.read(deliveryTrackingQuery.refreshProvider(id))),
              ),
          ]),
          loading: () => const ReadLoading(),
          error: (error, _) => ReadFeedback(
              title: 'Unable to load order.',
              message: AppFailure.safe(error).message,
              onRetry: refresh),
        ),
      ),
    );
  }
}
