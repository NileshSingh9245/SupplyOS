import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';

class Product {
  const Product._({
    required this.id,
    required this.sku,
    required this.name,
    required this.unit,
    required this.price,
    required this.gstRate,
    required this.currencyCode,
    this.categoryId,
  });

  final String id;
  final String sku;
  final String name;
  final String unit;
  final ServerDecimal price;
  final ServerDecimal gstRate;
  final String currencyCode;
  final String? categoryId;

  factory Product.fromJson(Object? input) {
    final json = JsonObject(input);
    final price = json.decimal('price');
    final gst = json.decimal('gst_rate');
    final currency = json.string('currency_code');
    if (!RegExp(r'^\d{1,12}(?:\.\d{1,2})?$').hasMatch(price.text) ||
        !RegExp(r'^(?:100(?:\.0{1,2})?|\d{1,2}(?:\.\d{1,2})?)$')
            .hasMatch(gst.text) ||
        !RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
      throw invalidResponse;
    }
    return Product._(
      id: json.uuid('id'),
      sku: serverText(json.value('sku'), maxLength: 64),
      name: serverText(json.value('name'), maxLength: 255),
      unit: serverText(json.value('unit'), maxLength: 50),
      price: price,
      gstRate: gst,
      currencyCode: currency,
      categoryId: json.optionalUuid('category_id'),
    );
  }
}

class ProductDetail {
  const ProductDetail._({
    required this.product,
    this.description,
    this.barcode,
    this.hsnCode,
    this.imageUrl,
  });

  final Product product;
  final String? description;
  final String? barcode;
  final String? hsnCode;
  final String? imageUrl;

  factory ProductDetail.fromJson(Object? input) {
    final json = JsonObject(input);
    return ProductDetail._(
      product: Product.fromJson(input),
      description: json.optionalString('description'),
      barcode: json.optionalString('barcode'),
      hsnCode: json.optionalString('hsn_code'),
      imageUrl: json.optionalString('image_url'),
    );
  }
}

class ProductCategory {
  const ProductCategory._(this.id, this.name, this.parentId);

  final String id;
  final String name;
  final String? parentId;

  factory ProductCategory.fromJson(Object? input) {
    final json = JsonObject(input);
    final id = json.uuid('id');
    final parent = json.optionalUuid('parent_id');
    if (parent?.toLowerCase() == id.toLowerCase()) throw invalidResponse;
    return ProductCategory._(
        id, serverText(json.value('name'), maxLength: 120), parent);
  }
}
