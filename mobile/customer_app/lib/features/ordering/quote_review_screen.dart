import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_widgets.dart';
import '../../core/formatters.dart';
import '../auth/auth_provider.dart';
import 'order_quote.dart';
import 'ordering_provider.dart';

class QuoteReviewScreen extends ConsumerStatefulWidget {
  const QuoteReviewScreen({super.key});

  @override
  ConsumerState<QuoteReviewScreen> createState() => _QuoteReviewScreenState();
}

class _QuoteReviewScreenState extends ConsumerState<QuoteReviewScreen> {
  Timer? _expiry;
  String? _timedQuote;

  @override
  void dispose() {
    _expiry?.cancel();
    super.dispose();
  }

  Future<void> _run(Future<Object> Function() action) async {
    final scope = ref.read(authProvider).key;
    try {
      await action();
    } catch (error) {
      if (mounted && ref.read(authProvider).key == scope) {
        showCustomerFailure(context, error);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final scope = ref.watch(authProvider.select((value) => value.key));
    if (scope == null) return const SizedBox.shrink();
    final state = ref.watch(customerOrderingProvider);
    if (state.scope != scope) return const SizedBox.shrink();
    final owner = ref.read(customerOrderingProvider.notifier);
    final accepted = state.accepted;
    final quote = accepted?.quote;
    final now = ref.read(customerClockProvider)();
    if (_timedQuote != quote?.id) {
      _expiry?.cancel();
      _timedQuote = quote?.id;
      if (quote != null && !quote.expiredAt(now)) {
        _expiry = Timer(quote.expiresAt.value.difference(now.toUtc()), () {
          if (mounted) setState(() {});
        });
      }
    }
    final expired = quote?.expiredAt(now) ?? false;
    final confirmed = state.checkout.phase == MutationPhase.succeeded
        ? state.checkout.response?.value
        : null;
    final uncertainCheckout = state.checkout.phase == MutationPhase.uncertain;
    final checkoutRejected = state.checkout.phase == MutationPhase.rejected;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Review & checkout'),
        leading: IconButton(
            tooltip: 'Back to cart',
            onPressed: () => context.go('/cart'),
            icon: const Icon(Icons.arrow_back)),
        actions: [SessionLogoutButton(sessionProvider: authProvider)],
      ),
      body: CustomerList(children: [
        if (confirmed != null) ...[
          CustomerSection(
              title: 'Order confirmed',
              icon: Icons.check_circle_outline,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                        'The server accepted this order and reserved its items atomically. This is the original checkout receipt, not a live fulfilment status.'),
                    const SizedBox(height: 16),
                    DataField('Order number', confirmed.order.orderNumber),
                    DataField('Order ID', confirmed.order.id),
                    DataField('Accepted quote ID', confirmed.quoteId),
                    DataField('Original order status',
                        statusLabel(confirmed.order.status)),
                    DataField(
                        'Grand total',
                        formatMoney(confirmed.order.grandTotal,
                            confirmed.order.currencyCode)),
                    DataField('Payment mode', confirmed.order.paymentMode),
                    DataField('Payment status',
                        statusLabel(confirmed.order.paymentStatus)),
                    Wrap(spacing: 12, runSpacing: 12, children: [
                      FilledButton(
                          onPressed: () =>
                              context.go('/orders/${confirmed.order.id}'),
                          child: const Text('View order')),
                      OutlinedButton(
                          onPressed: () => context
                              .go('/orders/${confirmed.order.id}/tracking'),
                          child: const Text('Track delivery')),
                    ]),
                  ])),
          TextButton(
              onPressed: () => context.go('/catalog'),
              child: const Text('Continue shopping')),
        ] else if (state.quote.phase == MutationPhase.uncertain) ...[
          const CustomerNotice(
              'Quote response unknown. The original products, quantities and request key are retained. Recover this quote before requesting a different quote or editing the cart.',
              isError: true),
          _OriginalQuoteIntent(request: state.quote.request!),
          if (state.quote.failure != null)
            CustomerNotice(state.quote.failure!.message, isError: true),
          FilledButton.icon(
              onPressed: state.isBusy ? null : () => _run(owner.recoverQuote),
              icon: const Icon(Icons.sync),
              label: const Text('Recover original quote')),
        ] else if (quote == null) ...[
          if (state.isBusy) ...[
            const LinearProgressIndicator(
                semanticsLabel: 'Waiting for quote response'),
            const SizedBox(height: 16),
            const Text('Waiting for the server. Do not restart the request.'),
          ] else ...[
            const InlineReadState(title: 'No accepted quote to review.'),
            if (state.quote.failure != null)
              CustomerNotice(state.quote.failure!.message, isError: true),
            OutlinedButton(
                onPressed: () => context.go('/cart'),
                child: const Text('Return to cart')),
          ],
        ] else ...[
          if (uncertainCheckout) ...[
            const CustomerNotice(
                'Checkout outcome unknown. An order may already exist. Do not place another order. Recovery sends only the original quote ID, proof and idempotency key.',
                isError: true),
            const CustomerNotice(
                'Recovery is held in memory for this session. Keep the app open until a receipt is confirmed. After an app restart, check your orders before placing a replacement.'),
            DataField('Original request key',
                state.checkout.request!.idempotencyKey!),
            FilledButton.icon(
                onPressed:
                    state.isBusy ? null : () => _run(owner.recoverCheckout),
                icon: const Icon(Icons.sync),
                label: const Text('Recover original checkout')),
            const SizedBox(height: 20),
          ],
          if (checkoutRejected)
            const CustomerNotice(
                'Checkout was rejected by the server. Stock, credit or quote terms may have changed. Request and review a new quote explicitly; no replacement order is sent automatically.',
                isError: true),
          if (state.checkout.failure != null)
            CustomerNotice(state.checkout.failure!.message, isError: true),
          if (state.isBusy) ...[
            const LinearProgressIndicator(
                semanticsLabel: 'Waiting for original ordering response'),
            const SizedBox(height: 16),
            const Text(
                'Waiting for the original request. Navigation will not discard its outcome.'),
            const SizedBox(height: 16),
          ],
          if (expired && !uncertainCheckout)
            const CustomerNotice(
                'This quote has expired. Request a new quote and review its terms before placing an order.',
                isError: true),
          const CustomerNotice(
              'Review the server values below. A quote does not reserve stock or use credit. Checkout makes one atomic server decision.'),
          CustomerSection(
              title: 'Your server quote',
              icon: Icons.receipt_long_outlined,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    DataField('Quote ID', quote.id),
                    DataField('Warehouse ID', quote.warehouseId),
                    DataField(
                        'Valid until (server time)', quote.expiresAt.text),
                    DataField('Payment mode', quote.paymentMode),
                    if (accepted != null) ...[
                      DataField(
                          'Delivery address',
                          JsonObject(accepted.original.body)
                                  .optionalString('delivery_address') ??
                              'Not provided'),
                      DataField(
                          'Requested delivery date',
                          JsonObject(accepted.original.body)
                                  .optionalString('scheduled_delivery_date') ??
                              'Not scheduled'),
                      if (JsonObject(accepted.original.body)
                              .optionalString('notes') !=
                          null)
                        DataField(
                            'Order notes',
                            JsonObject(accepted.original.body)
                                .optionalString('notes')!),
                    ],
                    DataField('Subtotal',
                        formatMoney(quote.subtotal, quote.currencyCode)),
                    DataField('Tax total',
                        formatMoney(quote.taxTotal, quote.currencyCode)),
                    DataField('Grand total',
                        formatMoney(quote.grandTotal, quote.currencyCode)),
                  ])),
          for (final item in quote.items)
            CustomerSection(
                title: item.name,
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      DataField('SKU', item.sku),
                      DataField(
                          'Quantity', '${item.quantity.text} ${item.unit}'),
                      DataField('Unit price',
                          formatMoney(item.unitPrice, quote.currencyCode)),
                      DataField('Tax rate', '${item.gstRate.text}%'),
                      DataField('Line subtotal',
                          formatMoney(item.subtotal, quote.currencyCode)),
                      DataField('Line tax',
                          formatMoney(item.tax, quote.currencyCode)),
                      DataField('Line total',
                          formatMoney(item.total, quote.currencyCode)),
                    ])),
          CustomerSection(
              title: 'Stock observations from server',
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final observation in quote.availability) ...[
                      DataField(
                          'Product',
                          quote.items
                              .singleWhere((item) =>
                                  item.productId.toLowerCase() ==
                                  observation.productId.toLowerCase())
                              .name),
                      DataField('Required quantity',
                          observation.requiredQuantity.text),
                      DataField('Available quantity',
                          observation.availableQuantity.text),
                      const Divider(),
                    ],
                    const Text(
                        'These observations belong to this quote. Stock is validated again atomically at checkout.'),
                  ])),
          for (final blocker in quote.blockers)
            CustomerNotice(
                blocker == 'insufficient_stock'
                    ? 'Server blocker: insufficient stock for this cart.'
                    : 'Server blocker: the credit limit does not cover this order.',
                isError: true),
          FilledButton.icon(
            onPressed: state.isLocked ||
                    checkoutRejected ||
                    expired ||
                    quote.blockers.isNotEmpty
                ? null
                : () => _run(owner.checkout),
            icon: const Icon(Icons.lock_outline),
            label: const Text('Accept quote & place order'),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: state.isLocked ? null : () => _run(owner.requestQuote),
            icon: const Icon(Icons.refresh),
            label: const Text('Request new quote'),
          ),
          const SizedBox(height: 12),
          TextButton(
              onPressed: state.isLocked ? null : () => context.go('/cart'),
              child: const Text('Edit cart')),
        ],
      ]),
    );
  }
}

class _OriginalQuoteIntent extends StatelessWidget {
  const _OriginalQuoteIntent({required this.request});
  final MutationRequest<OrderQuote> request;

  @override
  Widget build(BuildContext context) {
    final body = JsonObject(request.body);
    return CustomerSection(
        title: 'Frozen quote request',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          DataField('Original request key', request.idempotencyKey!),
          DataField('Warehouse ID', body.uuid('warehouse_id')),
          DataField('Payment mode', body.string('payment_mode')),
          for (final item in body.list('items', JsonObject.new)) ...[
            DataField('Product ID', item.uuid('product_id')),
            DataField('Exact requested quantity', item.string('quantity')),
          ],
        ]));
  }
}
