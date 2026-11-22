import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../core/contracts.dart';
import '../core/forms.dart';
import '../core/intents.dart';
import '../core/navigation.dart';
import '../core/providers.dart';
import '../core/widgets.dart';

typedef SearchPage = ({int page, String q});

class ProductRecord {
  ProductRecord(Object? input) {
    final json = JsonObject(input);
    id = json.uuid('id');
    sku = json.string('sku');
    name = json.string('name');
    unit = json.string('unit');
    basePrice = json.decimal('base_price');
    gstRate = json.decimal('gst_rate');
    packSize = json.decimal('pack_size');
    active = json.boolean('is_active');
    mrp = json.value('mrp') == null ? null : json.decimal('mrp');
    reorder = json.integer('reorder_level');
    threshold = json.integer('low_stock_threshold');
    description = json.optionalString('description');
    categoryId = json.optionalUuid('category_id');
    barcode = json.optionalString('barcode');
    hsn = json.optionalString('hsn_code');
  }
  late final String id, sku, name, unit;
  late final ServerDecimal basePrice, gstRate, packSize;
  late final ServerDecimal? mrp;
  late final int reorder, threshold;
  late final bool active;
  late final String? description, categoryId, barcode, hsn;
  FieldChoice get choice =>
      FieldChoice(id, '$sku / $name', '$unit / base ${basePrice.text}');
}

class CategoryRecord {
  CategoryRecord(Object? input) {
    final json = JsonObject(input);
    id = json.uuid('id');
    name = json.string('name');
    parentId = json.optionalUuid('parent_id');
  }
  late final String id, name;
  late final String? parentId;
}

final productsQuery = SessionQuery<Paginated<ProductRecord>, SearchPage>(
  sessionProvider: authProvider,
  load: (session, scope, arg, token) => AdminRepository(session).read(
    '/products',
    scope,
    token,
    (raw) {
      final page = Paginated.fromJson(raw, ProductRecord.new);
      page.requirePage(arg.page, 50);
      return page;
    },
    parameters: {
      'page': arg.page,
      'page_size': 50,
      if (arg.q.isNotEmpty) 'q': arg.q,
    },
  ),
);

final productQuery = SessionQuery<ProductRecord, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) =>
      AdminRepository(session)
          .read('/products/${idPath(id)}', scope, token, (raw) {
            final result = ProductRecord(raw);
            bindId(result.id, id);
            return result;
          }),
);

final categoriesQuery = SessionQuery<List<CategoryRecord>, int>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) => AdminRepository(session).read(
    '/products/categories',
    scope,
    token,
    (raw) => jsonList(raw, CategoryRecord.new),
  ),
);

final categoryQuery = SessionQuery<CategoryRecord, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) =>
      AdminRepository(session)
          .read('/products/categories', scope, token, (raw) {
            final category = jsonList(
              raw,
              CategoryRecord.new,
            ).where((row) => row.id == idPath(id)).firstOrNull;
            if (category == null) throw const AppFailure(FailureKind.notFound);
            return category;
          }),
);

class ProductInput implements AdminInput {
  const ProductInput({
    required this.name,
    required this.unit,
    required this.basePrice,
    required this.gstRate,
    required this.packSize,
    this.sku,
    this.description,
    this.categoryId,
    this.barcode,
    this.hsn,
    this.active = true,
    this.mrp = '',
    this.reorder = 0,
    this.threshold = 10,
  });
  final String name, unit, basePrice, gstRate, packSize;
  final String? sku, description, categoryId, barcode, hsn;
  final bool active;
  final String mrp;
  final int reorder, threshold;
  @override
  Map<String, Object?> toJson() => {
    if (sku != null) 'sku': textInput(sku!, 64, required: true),
    'name': textInput(name, 255, required: true),
    'unit': textInput(unit, 20, required: true),
    'base_price': decimalInput(basePrice),
    'gst_rate': decimalInput(gstRate),
    'pack_size': decimalInput(packSize, places: 3, positive: true),
    'mrp': mrp.trim().isEmpty ? null : decimalInput(mrp),
    'reorder_level': reorder,
    'low_stock_threshold': threshold,
    'description': optionalText(description ?? '', 2000),
    'barcode': optionalText(barcode ?? '', 80),
    'hsn_code': optionalText(hsn ?? '', 20),
    'category_id': categoryId == null || categoryId == ''
        ? null
        : idPath(categoryId!),
    if (sku == null) 'is_active': active,
  };
}

AdminCommand<ProductInput, ProductRecord> productCommand([String? id]) =>
    AdminCommand(
      slot: id == null ? 'product:create' : 'product:$id:edit',
      title: id == null ? 'Create product' : 'Save product',
      route: id == null ? '/products/new' : '/products/$id/edit',
      group: id == null ? 'product:create' : 'product:$id',
      roles: operators,
      endpoint: JsonMutationEndpoint(
        method: id == null ? MutationMethod.post : MutationMethod.patch,
        path: id == null ? '/products' : '/products/${idPath(id)}',
        expectedStatus: id == null ? 201 : 200,
        encode: (input) => input.toJson(),
        decode: (raw, original) {
          final value = ProductRecord(raw);
          final body = original.body!;
          if (id != null) bindId(value.id, id);
          if (value.name != body['name'] ||
              value.unit != body['unit'] ||
              value.categoryId != body['category_id'] ||
              value.description != body['description'] ||
              value.barcode != body['barcode'] ||
              value.hsn != body['hsn_code'] ||
              value.reorder != body['reorder_level'] ||
              value.threshold != body['low_stock_threshold'] ||
              (body.containsKey('sku') && value.sku != body['sku']) ||
              (body.containsKey('is_active') &&
                  value.active != body['is_active'])) {
            throw invalidResponse;
          }
          requireDecimalBinding(value.basePrice, body['base_price']);
          requireDecimalBinding(value.gstRate, body['gst_rate']);
          requireDecimalBinding(value.packSize, body['pack_size']);
          if (body['mrp'] == null) {
            if (value.mrp != null) throw invalidResponse;
          } else {
            if (value.mrp == null) throw invalidResponse;
            requireDecimalBinding(value.mrp!, body['mrp']);
          }
          return value;
        },
      ),
    );

class CategoryInput implements AdminInput {
  const CategoryInput(this.name, this.parentId);
  final String name;
  final String? parentId;
  @override
  Map<String, Object?> toJson() => {
    'name': textInput(name, 120, required: true),
    'parent_id': parentId == null || parentId == '' ? null : idPath(parentId!),
  };
}

final categoryCommand = AdminCommand<CategoryInput, CategoryRecord>(
  slot: 'category:create',
  title: 'Create category',
  route: '/products/categories',
  roles: operators,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/products/categories',
    expectedStatus: 201,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = CategoryRecord(raw);
      if (value.name != original.body!['name'] ||
          value.parentId != original.body!['parent_id']) {
        throw invalidResponse;
      }
      return value;
    },
  ),
);

Future<FieldChoice?> pickProduct(BuildContext context, WidgetRef ref) =>
    pickRecord(
      context,
      title: 'product',
      query: productsQuery,
      choice: (ProductRecord product) => product.choice,
    );

class ProductsScreen extends ConsumerStatefulWidget {
  const ProductsScreen({super.key});
  @override
  ConsumerState<ProductsScreen> createState() => _ProductsScreenState();
}

class _ProductsScreenState extends ConsumerState<ProductsScreen> {
  int page = 1;
  String q = '';
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Catalog / server base prices',
    title: 'Products',
    actions: [
      FilledButton.icon(
        onPressed: () => context.go('/products/new'),
        icon: const Icon(Icons.add),
        label: const Text('Create product'),
      ),
      recordLink(context, '/products/categories', 'Categories'),
      OutlinedButton.icon(
        onPressed: ref.read(productsQuery.refreshProvider((page: page, q: q))),
        icon: const Icon(Icons.refresh),
        label: const Text('Refresh'),
      ),
    ],
    children: [
      SearchBox(
        label: 'Search name or SKU',
        onSearch: (value) => setState(() {
          q = value;
          page = 1;
        }),
      ),
      QueryPanel(
        query: productsQuery,
        argument: (page: page, q: q),
        builder: (result) => Column(
          children: [
            if (result.items.isEmpty)
              const EmptyNotice('No products match this search.'),
            for (final product in result.items)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  label: product.sku,
                  title: product.name,
                  status: product.active ? 'active' : 'inactive',
                  lines: {
                    'Base price': product.basePrice.text,
                    'Unit / pack size':
                        '${product.unit} / ${product.packSize.text}',
                    'GST rate': product.gstRate.text,
                  },
                  onTap: () => context.go('/products/${product.id}'),
                ),
              ),
            AdminPageControls(
              page: result.page,
              total: result.total,
              hasNext: result.hasNext,
              onPage: (value) => setState(() => page = value),
            ),
          ],
        ),
      ),
    ],
  );
}

class ProductDetailScreen extends ConsumerWidget {
  const ProductDetailScreen(this.id, {super.key});
  final String id;
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Product record',
    title: 'Product detail',
    actions: [
      recordLink(context, '/products/$id/edit', 'Edit product'),
      recordLink(context, '/products', 'All products'),
      OutlinedButton(
        onPressed: ref.read(productQuery.refreshProvider(id)),
        child: const Text('Refresh server record'),
      ),
    ],
    children: [
      QueryPanel(
        query: productQuery,
        argument: id,
        builder: (product) => RecordCard(
          label: product.sku,
          title: product.name,
          status: product.active ? 'active' : 'inactive',
          lines: {
            'Unit': product.unit,
            'Pack size': product.packSize.text,
            'Base price': product.basePrice.text,
            'GST rate': product.gstRate.text,
            'Description': product.description ?? 'Not set',
            'Barcode': product.barcode ?? 'Not set',
            'HSN': product.hsn ?? 'Not set',
            'Category': product.categoryId ?? 'Uncategorized',
            'MRP': product.mrp?.text ?? 'Not set',
            'Reorder level': '${product.reorder}',
            'Low-stock threshold': '${product.threshold}',
          },
        ),
      ),
      const CapabilityNotice(
        'Prices shown here are product bases. Customer-effective prices and order amounts are resolved by the server; images/labels/scanning are not implemented transports.',
      ),
    ],
  );
}

class ProductEditScreen extends ConsumerWidget {
  const ProductEditScreen({this.id, super.key});
  final String? id;
  Widget _form(
    BuildContext context,
    WidgetRef ref,
    ProductRecord? product,
    List<CategoryRecord> categories,
  ) => IntentForm(
    key: ValueKey('product:${id ?? 'new'}'),
    command: productCommand(id),
    fields: [
      if (product == null)
        const AdminField('sku', 'SKU', required: true, maxLength: 64),
      AdminField(
        'name',
        'Product name',
        initial: product?.name ?? '',
        required: true,
        maxLength: 255,
      ),
      AdminField(
        'unit',
        'Unit',
        initial: product?.unit ?? 'pcs',
        required: true,
        maxLength: 20,
      ),
      AdminField(
        'base_price',
        'Base price',
        initial: product?.basePrice.text ?? '',
        required: true,
        kind: FieldKind.decimal,
      ),
      AdminField(
        'gst_rate',
        'GST rate (%)',
        initial: product?.gstRate.text ?? '0.00',
        required: true,
        kind: FieldKind.decimal,
      ),
      AdminField(
        'pack_size',
        'Pack size',
        initial: product?.packSize.text ?? '1.000',
        required: true,
        kind: FieldKind.decimal,
        places: 3,
      ),
      AdminField(
        'mrp',
        'MRP (optional)',
        initial: product?.mrp?.text ?? '',
        kind: FieldKind.decimal,
      ),
      AdminField(
        'reorder_level',
        'Server reorder level',
        initial: '${product?.reorder ?? 0}',
        kind: FieldKind.integer,
        required: true,
      ),
      AdminField(
        'low_stock_threshold',
        'Server low-stock threshold',
        initial: '${product?.threshold ?? 10}',
        kind: FieldKind.integer,
        required: true,
      ),
      AdminField(
        'category_id',
        'Category',
        initial: product?.categoryId ?? '',
        kind: FieldKind.choice,
        choices: {
          '': 'Uncategorized',
          for (final category in categories) category.id: category.name,
        },
      ),
      AdminField(
        'description',
        'Description',
        initial: product?.description ?? '',
        kind: FieldKind.multiline,
        maxLength: 2000,
      ),
      AdminField(
        'barcode',
        'Barcode',
        initial: product?.barcode ?? '',
        maxLength: 80,
      ),
      AdminField(
        'hsn_code',
        'HSN code',
        initial: product?.hsn ?? '',
        maxLength: 20,
      ),
      if (product != null)
        AdminField(
          'is_active',
          'Active product',
          initial: product.active,
          kind: FieldKind.boolean,
        ),
    ],
    input: (values) => ProductInput(
      sku: product == null ? values.text('sku') : null,
      name: values.text('name'),
      unit: values.text('unit'),
      basePrice: values.text('base_price'),
      gstRate: values.text('gst_rate'),
      packSize: values.text('pack_size'),
      mrp: values.text('mrp'),
      reorder: values.integer('reorder_level'),
      threshold: values.integer('low_stock_threshold'),
      description: values.text('description'),
      categoryId: values.text('category_id'),
      barcode: values.text('barcode'),
      hsn: values.text('hsn_code'),
      active: values.boolean('is_active'),
    ),
    onSaved: (value) {
      ref.invalidate(productsQuery.provider);
      ref.invalidate(productQuery.provider);
      context.go('/products/${value.id}');
    },
  );
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Catalog / authorized edits',
    title: id == null ? 'New product' : 'Edit product',
    children: [
      QueryPanel(
        query: categoriesQuery,
        argument: 0,
        builder: (categories) => id == null
            ? _form(context, ref, null, categories)
            : QueryPanel(
                query: productQuery,
                argument: id!,
                builder: (product) => _form(context, ref, product, categories),
              ),
      ),
    ],
  );
}

class CategoriesScreen extends ConsumerStatefulWidget {
  const CategoriesScreen({super.key});
  @override
  ConsumerState<CategoriesScreen> createState() => _CategoriesScreenState();
}

class _CategoriesScreenState extends ConsumerState<CategoriesScreen> {
  String search = '';
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Catalog classification',
    title: 'Categories',
    actions: [
      recordLink(context, '/products', 'Products'),
      OutlinedButton(
        onPressed: ref.read(categoriesQuery.refreshProvider(0)),
        child: const Text('Refresh'),
      ),
    ],
    children: [
      SearchBox(
        label: 'Search categories',
        onSearch: (value) => setState(() => search = value.toLowerCase()),
      ),
      QueryPanel(
        query: categoriesQuery,
        argument: 0,
        builder: (categories) => Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (!categories.any(
              (category) => category.name.toLowerCase().contains(search),
            ))
              const EmptyNotice('No categories match this search.'),
            for (final category in categories.where(
              (category) => category.name.toLowerCase().contains(search),
            ))
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: category.name,
                  onTap: () =>
                      context.go('/products/categories/${category.id}'),
                  lines: {
                    'Parent': category.parentId == null
                        ? 'Top level'
                        : categories
                                  .where((p) => p.id == category.parentId)
                                  .firstOrNull
                                  ?.name ??
                              category.parentId!,
                  },
                ),
              ),
            const SizedBox(height: 16),
            IntentForm(
              command: categoryCommand,
              fields: [
                const AdminField(
                  'name',
                  'Category name',
                  required: true,
                  maxLength: 120,
                ),
                AdminField(
                  'parent_id',
                  'Parent category',
                  kind: FieldKind.choice,
                  choices: {
                    '': 'Top level',
                    for (final category in categories)
                      category.id: category.name,
                  },
                ),
              ],
              input: (values) =>
                  CategoryInput(values.text('name'), values.text('parent_id')),
              onSaved: (_) => ref.read(categoriesQuery.refreshProvider(0))(),
            ),
          ],
        ),
      ),
    ],
  );
}

class CategoryDetailScreen extends ConsumerWidget {
  const CategoryDetailScreen(this.id, {super.key});
  final String id;
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Actual catalog classification',
    title: 'Category detail',
    actions: [recordLink(context, '/products/categories', 'Categories')],
    children: [
      QueryPanel(
        query: categoryQuery,
        argument: id,
        builder: (category) => RecordCard(
          title: category.name,
          lines: {'Parent category': category.parentId ?? 'Top level'},
        ),
      ),
      const CapabilityNotice(
        'Category listing, detail and creation use the existing category contract. There is no category update/removal endpoint; no fake edit operation is offered.',
      ),
    ],
  );
}
