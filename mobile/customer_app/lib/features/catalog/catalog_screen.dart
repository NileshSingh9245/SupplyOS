import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_widgets.dart';
import '../auth/auth_provider.dart';
import '../ordering/ordering_provider.dart';
import 'catalog_provider.dart';
import 'product.dart';

class CatalogScreen extends ConsumerWidget {
  const CatalogScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scope = ref.watch(authProvider.select((state) => state.key));
    if (scope == null) return const SizedBox.shrink();
    final filter = ref.watch(catalogFilterProvider(scope));
    final async = ref.watch(catalogQuery.provider(filter));
    final categories = ref.watch(categoriesQuery.provider(null));
    final cart = ref.watch(customerOrderingProvider);
    final refresh = ref.read(catalogQuery.refreshProvider(filter));
    final data = async.asData?.value;
    void search(String text) {
      ref.read(catalogFilterProvider(scope).notifier).state =
          CatalogFilter(search: text, categoryId: filter.categoryId);
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Catalog'), actions: [
        IconButton(
            tooltip: 'Refresh catalog',
            onPressed: async.isLoading ? null : refresh,
            icon: const Icon(Icons.refresh)),
        IconButton(
          tooltip: 'Open cart',
          onPressed: () => context.go('/cart'),
          icon: Badge.count(
              count: cart.lines.length,
              isLabelVisible: cart.lines.isNotEmpty,
              child: const Icon(Icons.shopping_bag_outlined)),
        ),
        SessionLogoutButton(sessionProvider: authProvider),
      ]),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: CustomerList(children: [
          Text('Your next supply run',
              style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          const Text(
              'Your customer price before tax. A new order is priced again by the server.'),
          const SizedBox(height: 20),
          CustomerSearch(
              key: ValueKey(scope),
              label: 'Search products or SKU',
              initialText: filter.search,
              onSearch: search),
          const SizedBox(height: 12),
          categories.when(
            skipLoadingOnReload: false,
            skipLoadingOnRefresh: false,
            data: (rows) => SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(children: [
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: const Text('All categories'),
                    selected: filter.categoryId == null,
                    onSelected: (_) => ref
                        .read(catalogFilterProvider(scope).notifier)
                        .state = CatalogFilter(search: filter.search),
                  ),
                ),
                for (final category in rows)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(category.name),
                      selected: filter.categoryId == category.id,
                      onSelected: (_) => ref
                              .read(catalogFilterProvider(scope).notifier)
                              .state =
                          CatalogFilter(
                              search: filter.search, categoryId: category.id),
                    ),
                  ),
              ]),
            ),
            loading: () => const LinearProgressIndicator(
                semanticsLabel: 'Loading categories'),
            error: (_, __) => Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: ref.read(categoriesQuery.refreshProvider(null)),
                icon: const Icon(Icons.refresh),
                label: const Text('Retry categories'),
              ),
            ),
          ),
          const SizedBox(height: 20),
          async.when(
            skipLoadingOnRefresh: false,
            skipLoadingOnReload: false,
            data: (products) => products.items.isEmpty
                ? const InlineReadState(title: 'No products available.')
                : LayoutBuilder(builder: (context, constraints) {
                    final width = constraints.maxWidth >= 700
                        ? (constraints.maxWidth - 16) / 2
                        : constraints.maxWidth;
                    return Wrap(spacing: 16, runSpacing: 16, children: [
                      for (final product in products.items)
                        SizedBox(
                            width: width,
                            child:
                                _ProductCard(product: product, scope: scope)),
                    ]);
                  }),
            loading: () => const SizedBox(height: 240, child: ReadLoading()),
            error: (error, stack) => InlineReadState(
              title: 'Unable to load catalog.',
              error: error,
              onRetry: refresh,
            ),
          ),
          if (data != null)
            PageControls(
              page: data.page,
              total: data.total,
              onPrevious: data.hasPrevious
                  ? () => ref
                      .read(catalogFilterProvider(scope).notifier)
                      .state = filter.atPage(filter.page - 1)
                  : null,
              onNext: data.hasNext
                  ? () => ref
                      .read(catalogFilterProvider(scope).notifier)
                      .state = filter.atPage(filter.page + 1)
                  : null,
            ),
        ]),
      ),
    );
  }
}

class _ProductCard extends ConsumerWidget {
  const _ProductCard({required this.product, required this.scope});
  final Product product;
  final SessionKey scope;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cart = ref.watch(customerOrderingProvider);
    final inCart = cart.lineFor(product.id) != null;
    return CustomerSection(
      title: product.name,
      icon: Icons.inventory_2_outlined,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${product.sku} / per ${product.unit}'),
        const SizedBox(height: 8),
        Text('${product.currencyCode} ${product.price.text}',
            style: Theme.of(context).textTheme.titleLarge),
        Text('Tax rate: ${product.gstRate.text}%'),
        const SizedBox(height: 16),
        Wrap(spacing: 12, runSpacing: 8, children: [
          OutlinedButton(
            onPressed: () => context.go('/catalog/${product.id}'),
            child: const Text('View product'),
          ),
          FilledButton(
            onPressed: cart.isLocked
                ? null
                : () {
                    if (inCart) {
                      context.go('/cart');
                      return;
                    }
                    try {
                      ref
                          .read(customerOrderingProvider.notifier)
                          .setLine(product, '1', scope: scope);
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                          content: Text('${product.name} added to cart.')));
                    } catch (error) {
                      showCustomerFailure(context, error);
                    }
                  },
            child: Text(inCart ? 'Edit quantity' : 'Add 1 to cart'),
          ),
        ]),
      ]),
    );
  }
}
