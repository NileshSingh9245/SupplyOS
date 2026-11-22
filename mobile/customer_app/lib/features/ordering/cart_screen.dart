import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';
import '../../core/customer_widgets.dart';
import '../account/account_provider.dart';
import '../auth/auth_provider.dart';
import 'ordering_provider.dart';

class CartScreen extends ConsumerWidget {
  const CartScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scope = ref.watch(authProvider.select((value) => value.key));
    if (scope == null) return const SizedBox.shrink();
    final cart = ref.watch(customerOrderingProvider);
    if (cart.scope != scope) return const SizedBox.shrink();
    return Scaffold(
      appBar: AppBar(title: const Text('Your cart'), actions: [
        SessionLogoutButton(sessionProvider: authProvider),
      ]),
      body: cart.lines.isEmpty
          ? CustomerList(children: [
              if (cart.lastReceipt != null)
                CustomerSection(
                    title: 'Order confirmed',
                    icon: Icons.check_circle_outline,
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(cart.lastReceipt!.order.orderNumber),
                          const SizedBox(height: 12),
                          FilledButton(
                              onPressed: () => context
                                  .go('/orders/${cart.lastReceipt!.order.id}'),
                              child: const Text('View confirmed order')),
                        ])),
              const CustomerSection(
                  title: 'Make room for your next order',
                  icon: Icons.shopping_bag_outlined,
                  child: Text(
                      'Your cart is empty. Choose products and exact quantities from the catalog.')),
              FilledButton.icon(
                  onPressed: () => context.go('/catalog'),
                  icon: const Icon(Icons.add),
                  label: const Text('Browse products')),
            ])
          : _CartForm(key: ValueKey(scope), scope: scope),
    );
  }
}

class _CartForm extends ConsumerStatefulWidget {
  const _CartForm({required this.scope, super.key});
  final SessionKey scope;

  @override
  ConsumerState<_CartForm> createState() => _CartFormState();
}

class _CartFormState extends ConsumerState<_CartForm> {
  final _form = GlobalKey<FormState>();
  final _quantityDrafts = <String, String>{};
  late String? _warehouseDraft =
      ref.read(customerOrderingProvider).warehouse?.id;
  Future<void>? _observedRenewal;
  late final _address = TextEditingController(
      text: ref.read(customerOrderingProvider).deliveryAddress);
  late final _date = TextEditingController(
      text: ref.read(customerOrderingProvider).scheduledDeliveryDate);
  late final _notes =
      TextEditingController(text: ref.read(customerOrderingProvider).notes);

  @override
  void dispose() {
    _address.dispose();
    _date.dispose();
    _notes.dispose();
    super.dispose();
  }

  void edit(VoidCallback change) {
    try {
      change();
    } catch (error) {
      showCustomerFailure(context, error);
      if (mounted) setState(() {});
    }
  }

  Future<void> _requestQuote() async {
    final lines = ref.read(customerOrderingProvider).lines;
    final invalidQuantity = lines.any((line) =>
        quantityError(_quantityDrafts[line.productId] ?? line.quantity) !=
        null);
    if (!_form.currentState!.validate() || invalidQuantity) {
      showCustomerFailure(context, const AppFailure(FailureKind.validation));
      return;
    }
    final previousRequest = ref.read(customerOrderingProvider).quote.request;
    try {
      final owner = ref.read(customerOrderingProvider.notifier);
      final active =
          ref.read(activeWarehousesQuery.provider(null)).asData?.value;
      if (active == null || _warehouseDraft == null) {
        throw const AppFailure(FailureKind.validation);
      }
      owner.chooseWarehouse(
          active.singleWhere((row) => row.id == _warehouseDraft),
          scope: widget.scope);
      for (final line in lines) {
        owner.setLine(
            line.product, _quantityDrafts[line.productId] ?? line.quantity,
            scope: widget.scope);
      }
      owner.setDelivery(
          address: _address.text,
          date: _date.text,
          notes: _notes.text,
          scope: widget.scope);
      await owner.requestQuote();
    } catch (error) {
      if (!mounted || ref.read(authProvider).key != widget.scope) return;
      final request = ref.read(customerOrderingProvider).quote.request;
      if (request == null || identical(request, previousRequest)) {
        showCustomerFailure(context, error);
        return;
      }
    }
    if (mounted && ref.read(authProvider).key == widget.scope) {
      context.go('/cart/quote');
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = ref.watch(customerOrderingProvider);
    final owner = ref.read(customerOrderingProvider.notifier);
    final warehouses = ref.watch(activeWarehousesQuery.provider(null));
    final profile = ref.watch(customerProfileQuery.provider(null));
    final active = warehouses.asData?.value;
    final account = profile.asData?.value;
    final warehouseId =
        active != null && active.any((row) => row.id == _warehouseDraft)
            ? _warehouseDraft
            : null;
    final renewal =
        ref.read(authProvider.notifier).pendingRenewalForScope(widget.scope);
    if (renewal != null && !identical(renewal, _observedRenewal)) {
      _observedRenewal = renewal;
      void resumed() {
        if (mounted && ref.read(authProvider).key == widget.scope) {
          setState(() {});
        }
      }

      unawaited(renewal.then<void>((_) => resumed(),
          onError: (Object error, StackTrace trace) => resumed()));
    }
    final editable = !cart.isLocked && renewal == null;
    return Form(
        key: _form,
        child: CustomerList(children: [
          const CustomerNotice(
              'Your cart stores product IDs and exact quantities. Prices, tax, stock and credit are checked by the server when you request a quote.'),
          if (renewal != null)
            const CustomerNotice(
                'Checking session authorization. Cart edits and new quotes wait for verification.'),
          if (cart.checkout.phase == MutationPhase.uncertain)
            const CustomerNotice(
                'Checkout outcome unknown. Your original cart and accepted quote are locked. Recover the original checkout before making another order.',
                isError: true),
          if (cart.quote.phase == MutationPhase.uncertain)
            const CustomerNotice(
                'The quote response was not confirmed. Recover the original quote before editing this cart.',
                isError: true),
          if (cart.failure != null)
            CustomerNotice(cart.failure!.message, isError: true),
          for (final line in cart.lines)
            CustomerSection(
                key: ValueKey(line.productId),
                title: line.product.name,
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text('${line.product.sku} / ${line.product.unit}'),
                      const SizedBox(height: 12),
                      TextFormField(
                        key: ValueKey('cart-quantity-${line.productId}'),
                        initialValue:
                            _quantityDrafts[line.productId] ?? line.quantity,
                        enabled: editable,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                        decoration: InputDecoration(
                            labelText: 'Quantity in ${line.product.unit}',
                            helperText: 'Kept as exact decimal text.'),
                        validator: quantityError,
                        onChanged: (value) {
                          _quantityDrafts[line.productId] = value;
                          if (isQuantityText(value)) {
                            edit(() => owner.setLine(line.product, value,
                                scope: widget.scope));
                          }
                        },
                      ),
                      const SizedBox(height: 8),
                      Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton.icon(
                            onPressed: editable
                                ? () => edit(() => owner.removeLine(
                                    line.productId,
                                    scope: widget.scope))
                                : null,
                            icon: const Icon(Icons.delete_outline),
                            label: const Text('Remove product'),
                          )),
                    ])),
          CustomerSection(
              title: 'Where and how',
              icon: Icons.local_shipping_outlined,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    warehouses.when(
                      skipLoadingOnRefresh: false,
                      skipLoadingOnReload: false,
                      data: (rows) => rows.isEmpty
                          ? const CustomerNotice(
                              'No active warehouse is available. A warehouse is required for a quote.',
                              isError: true)
                          : DropdownButtonFormField<String>(
                              key: ValueKey((
                                warehouseId,
                                rows.map((row) => row.id).join(',')
                              )),
                              initialValue: warehouseId,
                              isExpanded: true,
                              itemHeight: null,
                              decoration: const InputDecoration(
                                  labelText: 'Fulfilment warehouse',
                                  helperText:
                                      'Only active warehouses are offered. Eligibility is validated by the server.'),
                              items: [
                                for (final row in rows)
                                  DropdownMenuItem(
                                      value: row.id, child: Text(row.name))
                              ],
                              onChanged: editable
                                  ? (id) {
                                      setState(() => _warehouseDraft = id);
                                      edit(() => owner.chooseWarehouse(
                                          id == null
                                              ? null
                                              : rows.singleWhere(
                                                  (row) => row.id == id),
                                          scope: widget.scope));
                                    }
                                  : null,
                              validator: (value) => value == null
                                  ? 'Choose an active warehouse.'
                                  : null,
                            ),
                      loading: () => const LinearProgressIndicator(
                          semanticsLabel: 'Loading active warehouses'),
                      error: (error, _) => InlineReadState(
                          title: 'Unable to load warehouses.',
                          error: error,
                          onRetry: ref.read(
                              activeWarehousesQuery.refreshProvider(null))),
                    ),
                    const SizedBox(height: 8),
                    Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton.icon(
                          onPressed: warehouses.isLoading || cart.isBusy
                              ? null
                              : ref.read(
                                  activeWarehousesQuery.refreshProvider(null)),
                          icon: const Icon(Icons.refresh),
                          label: const Text('Refresh active warehouses'),
                        )),
                    const SizedBox(height: 12),
                    Text('Payment mode',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Wrap(spacing: 12, runSpacing: 8, children: [
                      ChoiceChip(
                          label: const Text('Cash'),
                          selected: cart.paymentMode == 'cash',
                          onSelected: editable
                              ? (_) => edit(() => owner.choosePaymentMode(
                                  'cash',
                                  scope: widget.scope))
                              : null),
                      ChoiceChip(
                          label: const Text('Credit'),
                          selected: cart.paymentMode == 'credit',
                          onSelected:
                              editable && account?.customerType == 'credit'
                                  ? (_) => edit(() => owner.choosePaymentMode(
                                      'credit',
                                      scope: widget.scope))
                                  : null),
                    ]),
                    const SizedBox(height: 8),
                    if (account?.customerType != 'credit')
                      const Text(
                          'Credit requires an eligible credit account. Server checks apply.'),
                    const SizedBox(height: 20),
                    TextFormField(
                      key: const ValueKey('delivery-address'),
                      controller: _address,
                      enabled: editable,
                      minLines: 2,
                      maxLines: 5,
                      maxLength: 500,
                      decoration: const InputDecoration(
                          labelText: 'Delivery address',
                          helperText:
                              'Optional. Use your account address or enter a delivery address.'),
                      onChanged: (value) => edit(() => owner.setDelivery(
                          address: value, scope: widget.scope)),
                    ),
                    if (account?.address != null &&
                        account!.address!.isNotEmpty)
                      Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton.icon(
                            onPressed: editable
                                ? () {
                                    _address.text = account.address!;
                                    edit(() => owner.setDelivery(
                                        address: _address.text,
                                        scope: widget.scope));
                                  }
                                : null,
                            icon: const Icon(Icons.home_outlined),
                            label: const Text('Use account address'),
                          )),
                    TextFormField(
                      key: const ValueKey('delivery-date'),
                      controller: _date,
                      enabled: editable,
                      maxLength: 10,
                      keyboardType: TextInputType.datetime,
                      decoration: const InputDecoration(
                          labelText: 'Requested delivery date',
                          helperText:
                              'YYYY-MM-DD, optional. This is a request, not a delivery guarantee.'),
                      validator: (value) {
                        if (value == null || value.isEmpty) return null;
                        try {
                          ServerDate.parse(value);
                          return null;
                        } catch (_) {
                          return 'Enter a valid date as YYYY-MM-DD.';
                        }
                      },
                      onChanged: (value) => edit(() =>
                          owner.setDelivery(date: value, scope: widget.scope)),
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      key: const ValueKey('order-notes'),
                      controller: _notes,
                      enabled: editable,
                      maxLines: 3,
                      maxLength: 500,
                      decoration: const InputDecoration(
                          labelText: 'Order notes',
                          helperText:
                              'Optional instructions for the business.'),
                      onChanged: (value) => edit(() =>
                          owner.setDelivery(notes: value, scope: widget.scope)),
                    ),
                    profile.when(
                      data: (value) => value.isActive
                          ? const SizedBox.shrink()
                          : const CustomerNotice(
                              'Your customer profile is inactive.',
                              isError: true),
                      loading: () => const LinearProgressIndicator(
                          semanticsLabel: 'Checking your customer profile'),
                      error: (error, _) => InlineReadState(
                          title: 'Unable to check your account.',
                          error: error,
                          onRetry: ref.read(
                              customerProfileQuery.refreshProvider(null))),
                    ),
                  ])),
          if (cart.isBusy)
            const LinearProgressIndicator(
                semanticsLabel: 'Preparing ordering request'),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed:
                editable && warehouseId != null && account?.isActive == true
                    ? _requestQuote
                    : null,
            icon: const Icon(Icons.receipt_long_outlined),
            label: const Text('Get server quote'),
          ),
          if (cart.quote.request != null || cart.checkout.request != null) ...[
            const SizedBox(height: 12),
            OutlinedButton(
                onPressed: () => context.go('/cart/quote'),
                child: Text(cart.isLocked
                    ? 'Open quote / checkout recovery'
                    : 'Review current quote')),
          ],
          const SizedBox(height: 12),
          TextButton(
              onPressed: () => context.go('/catalog'),
              child: const Text('Continue shopping')),
        ]));
  }
}
