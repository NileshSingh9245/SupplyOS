import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';
import '../../core/customer_widgets.dart';
import '../auth/auth_provider.dart';
import '../ordering/ordering_provider.dart';
import 'catalog_provider.dart';
import 'product.dart';

class ProductDetailScreen extends ConsumerWidget {
  const ProductDetailScreen({required this.id, super.key});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scope = ref.watch(authProvider.select((value) => value.key));
    if (scope == null) return const SizedBox.shrink();
    final data = ref.watch(productDetailQuery.provider(id));
    final refresh = ref.read(productDetailQuery.refreshProvider(id));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Product details'),
        leading: IconButton(
            tooltip: 'Back to catalog',
            onPressed: () => context.go('/catalog'),
            icon: const Icon(Icons.arrow_back)),
        actions: [
          IconButton(
              tooltip: 'Refresh product',
              onPressed: data.isLoading ? null : refresh,
              icon: const Icon(Icons.refresh)),
          SessionLogoutButton(sessionProvider: authProvider),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: data.when(
          skipLoadingOnReload: false,
          skipLoadingOnRefresh: false,
          data: (detail) => _ProductDetail(
              key: ValueKey((scope, id)), detail: detail, scope: scope),
          loading: () => const ReadLoading(),
          error: (error, _) => ReadFeedback(
              title: 'Unable to load product.',
              message: AppFailure.safe(error).message,
              onRetry: refresh),
        ),
      ),
    );
  }
}

class _ProductDetail extends ConsumerStatefulWidget {
  const _ProductDetail({required this.detail, required this.scope, super.key});
  final ProductDetail detail;
  final SessionKey scope;

  @override
  ConsumerState<_ProductDetail> createState() => _ProductDetailState();
}

class _ProductDetailState extends ConsumerState<_ProductDetail> {
  final _form = GlobalKey<FormState>();
  late final _quantity = TextEditingController(
      text: ref
              .read(customerOrderingProvider)
              .lineFor(widget.detail.product.id)
              ?.quantity ??
          '1');

  @override
  void dispose() {
    _quantity.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final detail = widget.detail;
    final product = detail.product;
    final cart = ref.watch(customerOrderingProvider);
    return CustomerList(children: [
      CustomerSection(
        title: product.name,
        icon: Icons.inventory_2_outlined,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          DataField('SKU', product.sku),
          DataField('Customer unit price before tax',
              '${product.currencyCode} ${product.price.text} / ${product.unit}'),
          DataField('Tax rate', '${product.gstRate.text}%'),
          if (detail.description != null)
            DataField('About this product', detail.description!),
          if (detail.hsnCode != null) DataField('HSN', detail.hsnCode!),
          if (detail.barcode != null) DataField('Barcode', detail.barcode!),
        ]),
      ),
      const CustomerNotice(
          'Catalog prices are informational. Review a server quote before placing your order.'),
      CustomerSection(
          title: 'Choose your quantity',
          child: Form(
            key: _form,
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextFormField(
                    key: const ValueKey('product-quantity'),
                    controller: _quantity,
                    enabled: !cart.isLocked,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    textInputAction: TextInputAction.done,
                    decoration: InputDecoration(
                        labelText: 'Quantity in ${product.unit}',
                        helperText: 'Exact quantity, up to 3 decimal places.'),
                    validator: quantityError,
                  ),
                  const SizedBox(height: 16),
                  FilledButton.icon(
                    onPressed: cart.isLocked
                        ? null
                        : () {
                            if (!_form.currentState!.validate()) return;
                            try {
                              ref
                                  .read(customerOrderingProvider.notifier)
                                  .setLine(product, _quantity.text,
                                      scope: widget.scope);
                              context.go('/cart');
                            } catch (error) {
                              showCustomerFailure(context, error);
                            }
                          },
                    icon: const Icon(Icons.shopping_bag_outlined),
                    label: Text(cart.lineFor(product.id) == null
                        ? 'Add to cart'
                        : 'Update cart'),
                  ),
                  if (cart.isLocked) ...[
                    const SizedBox(height: 12),
                    const Text(
                        'An ordering request is unresolved. Recover it in your cart before editing quantities.'),
                    TextButton(
                        onPressed: () => context.go('/cart/quote'),
                        child: const Text('Open order recovery')),
                  ],
                ]),
          )),
    ]);
  }
}
