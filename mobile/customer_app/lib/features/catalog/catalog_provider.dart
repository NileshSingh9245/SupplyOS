import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../auth/auth_provider.dart';
import 'product.dart';

const catalogPageSize = 50;

final catalogPageProvider =
    StateProvider.autoDispose.family<int, SessionKey>((ref, scope) => 1);

final productsQuery = SessionQuery<Paginated<Product>, int>(
  sessionProvider: authProvider,
  load: (session, scope, page, token) async {
    if (page < 1) throw invalidResponse;
    final data = await session.get(
      '/catalog',
      scope: scope,
      queryParameters: {'page': page, 'page_size': catalogPageSize},
      cancelToken: token,
    );
    final result = Paginated<Product>.fromJson(data, Product.fromJson);
    result.requirePage(page, catalogPageSize);
    return result;
  },
);

final productsProvider = productsQuery.provider;
