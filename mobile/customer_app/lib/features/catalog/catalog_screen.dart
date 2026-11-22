import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../auth/auth_provider.dart';
import 'catalog_provider.dart';

class CatalogScreen extends ConsumerWidget {
  const CatalogScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scope = ref.watch(authProvider.select((state) => state.key));
    if (scope == null) return const SizedBox.shrink();
    final page = ref.watch(catalogPageProvider(scope));
    final async = ref.watch(productsProvider(page));
    final refresh = ref.read(productsQuery.refreshProvider(page));
    final data = async.asData?.value;
    return Scaffold(
      appBar: AppBar(title: const Text('Catalog'), actions: [
        IconButton(
            tooltip: 'Refresh catalog',
            onPressed: async.isLoading ? null : refresh,
            icon: const Icon(Icons.refresh)),
        SessionLogoutButton(sessionProvider: authProvider),
      ]),
      body: Column(children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 8, 16, 8),
          child: Text(
              'Your customer price before tax. A new order is priced again by the server.'),
        ),
        Expanded(
            child: RefreshIndicator(
          onRefresh: refresh,
          child: async.when(
            skipLoadingOnRefresh: false,
            skipLoadingOnReload: false,
            data: (products) => products.items.isEmpty
                ? const ReadFeedback(title: 'No products available.')
                : ListView.separated(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.all(16),
                    itemCount: products.items.length,
                    separatorBuilder: (_, index) => const Divider(height: 1),
                    itemBuilder: (_, index) {
                      final product = products.items[index];
                      return ListTile(
                        title: Text(product.name),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('${product.sku} / per ${product.unit}'),
                            Text(
                                '${product.currencyCode} ${product.price.text}',
                                style: const TextStyle(
                                    fontWeight: FontWeight.w800)),
                            Text('Tax rate: ${product.gstRate.text}%'),
                          ],
                        ),
                      );
                    },
                  ),
            loading: () => const ReadLoading(),
            error: (error, stack) => ReadFeedback(
              title: 'Unable to load catalog.',
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
                ? () => ref.read(catalogPageProvider(scope).notifier).state =
                    page - 1
                : null,
            onNext: data.hasNext
                ? () => ref.read(catalogPageProvider(scope).notifier).state =
                    page + 1
                : null,
          ),
      ]),
    );
  }
}
