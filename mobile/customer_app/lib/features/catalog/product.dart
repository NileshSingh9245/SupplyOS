import 'package:supplyos_core/supplyos_core.dart';

class Product {
  const Product._({
    required this.id,
    required this.sku,
    required this.name,
    required this.unit,
    required this.price,
    required this.gstRate,
    required this.currencyCode,
  });

  final String id;
  final String sku;
  final String name;
  final String unit;
  final ServerDecimal price;
  final ServerDecimal gstRate;
  final String currencyCode;

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
      sku: json.string('sku'),
      name: json.string('name'),
      unit: json.string('unit'),
      price: price,
      gstRate: gst,
      currencyCode: currency,
    );
  }
}
