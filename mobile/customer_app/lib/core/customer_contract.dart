import 'package:supplyos_core/supplyos_core.dart';

ServerDecimal serverAmount(Object? value, {bool signed = false}) {
  final pattern =
      signed ? r'^-?\d{1,24}(?:\.\d{1,12})?$' : r'^\d{1,24}(?:\.\d{1,12})?$';
  if (value is! String || !RegExp(pattern).hasMatch(value)) {
    throw invalidResponse;
  }
  return ServerDecimal.parse(value);
}

String serverCurrency(Object? value) {
  if (value is! String || !RegExp(r'^[A-Z]{3}$').hasMatch(value)) {
    throw invalidResponse;
  }
  return value;
}

String serverText(Object? value,
    {int maxLength = 500, bool multiline = false}) {
  if (value is! String ||
      value.trim().isEmpty ||
      value.length > maxLength ||
      RegExp(multiline
              ? r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]'
              : r'[\x00-\x1F\x7F]')
          .hasMatch(value)) {
    throw invalidResponse;
  }
  return value;
}

bool isQuantityText(String value) =>
    RegExp(r'^(?:0|[1-9]\d{0,12})(?:\.\d{1,3})?$').hasMatch(value) &&
    RegExp(r'[1-9]').hasMatch(value);

String? quantityError(String? value) => value == null || !isQuantityText(value)
    ? 'Enter a positive quantity with up to 3 decimal places, for example 1.250.'
    : null;

ServerDecimal serverQuantity(Object? value, {bool allowZero = false}) {
  if (value is! String ||
      !RegExp(r'^\d{1,13}(?:\.\d{1,3})?$').hasMatch(value) ||
      (!allowZero && !RegExp(r'[1-9]').hasMatch(value))) {
    throw invalidResponse;
  }
  return ServerDecimal.parse(value);
}

ServerDecimal serverTaxRate(Object? value) {
  if (value is! String ||
      !RegExp(r'^(?:100(?:\.0{1,6})?|\d{1,2}(?:\.\d{1,6})?)$')
          .hasMatch(value)) {
    throw invalidResponse;
  }
  return ServerDecimal.parse(value);
}

// Compare decimal spellings for receipt binding, without computing any amounts.
bool sameDecimalText(String a, String b) {
  String canonical(String text) {
    final parts = text.split('.');
    final integer = parts.first.replaceFirst(RegExp(r'^0+(?=\d)'), '');
    final fraction =
        parts.length == 1 ? '' : parts[1].replaceFirst(RegExp(r'0+$'), '');
    return fraction.isEmpty ? integer : '$integer.$fraction';
  }

  return canonical(a) == canonical(b);
}

List<T> serverList<T>(Object? input, T Function(Object?) decode) {
  if (input is! List) throw invalidResponse;
  return List<T>.unmodifiable(input.map((Object? value) => decode(value)));
}

void requireUniqueIds<T>(Iterable<T> rows, String Function(T) id) {
  final seen = <String>{};
  for (final row in rows) {
    if (!seen.add(id(row).toLowerCase())) throw invalidResponse;
  }
}
