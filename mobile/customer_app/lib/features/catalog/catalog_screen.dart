import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/formatters.dart';

class Product {
  final String id, sku, name, unit;
  final String basePrice;
  Product({required this.id, required this.sku, required this.name,
    required this.unit, required this.basePrice});
  factory Product.fromJson(Map<String, dynamic> j) => Product(
    id: j['id'], sku: j['sku'], name: j['name'], unit: j['unit'],
    basePrice: j['base_price'].toString(),
  );
}

final productsProvider = FutureProvider<List<Product>>((ref) async {
  final dio = ref.read(apiProvider);
  final r = await dio.get('/products', queryParameters: {'page_size': 100});
  final items = (r.data['items'] as List).cast<Map<String, dynamic>>();
  return items.map(Product.fromJson).toList();
});

class CatalogScreen extends ConsumerWidget {
  const CatalogScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(productsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Catalog')),
      body: async.when(
        data: (products) => ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: products.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (_, i) {
            final p = products[i];
            return ListTile(
              title: Text(p.name),
              subtitle: Text('${p.sku} · per ${p.unit}'),
              trailing: Text(formatINR(p.basePrice),
                style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
            );
          },
        ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Failed to load: $e')),
      ),
    );
  }
}
