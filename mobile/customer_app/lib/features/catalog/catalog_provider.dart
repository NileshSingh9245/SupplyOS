import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';
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

class CatalogFilter {
  const CatalogFilter({this.page = 1, this.search = '', this.categoryId});

  final int page;
  final String search;
  final String? categoryId;

  CatalogFilter atPage(int value) =>
      CatalogFilter(page: value, search: search, categoryId: categoryId);

  Map<String, Object?> get parameters {
    if (page < 1 ||
        search.length > 200 ||
        (categoryId != null && !isUuid(categoryId!))) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
    return {
      'page': page,
      'page_size': catalogPageSize,
      if (search.isNotEmpty) 'q': search,
      if (categoryId != null) 'category_id': categoryId!.toLowerCase(),
    };
  }

  @override
  bool operator ==(Object other) =>
      other is CatalogFilter &&
      page == other.page &&
      search == other.search &&
      categoryId == other.categoryId;

  @override
  int get hashCode => Object.hash(page, search, categoryId);
}

final catalogFilterProvider = StateProvider.autoDispose
    .family<CatalogFilter, SessionKey>((ref, scope) => const CatalogFilter());

final catalogQuery = SessionQuery<Paginated<Product>, CatalogFilter>(
  sessionProvider: authProvider,
  load: (session, scope, filter, token) async {
    final data = await session.get('/catalog',
        scope: scope, queryParameters: filter.parameters, cancelToken: token);
    final result = Paginated<Product>.fromJson(data, Product.fromJson);
    result.requirePage(filter.page, catalogPageSize);
    requireUniqueIds(result.items, (product) => product.id);
    return result;
  },
);

final productDetailQuery = SessionQuery<ProductDetail, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) async {
    if (!isUuid(id)) throw invalidResponse;
    final detail = ProductDetail.fromJson(await session
        .get('/catalog/${id.toLowerCase()}', scope: scope, cancelToken: token));
    if (detail.product.id.toLowerCase() != id.toLowerCase()) {
      throw invalidResponse;
    }
    return detail;
  },
);

final categoriesQuery = SessionQuery<List<ProductCategory>, void>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) async {
    final rows = serverList(
        await session.get('/products/categories',
            scope: scope, cancelToken: token),
        ProductCategory.fromJson);
    requireUniqueIds(rows, (row) => row.id);
    return rows;
  },
);
