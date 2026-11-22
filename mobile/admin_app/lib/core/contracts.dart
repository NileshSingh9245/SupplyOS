import 'package:supplyos_core/supplyos_core.dart';

String idPath(String id) {
  if (!isUuid(id)) throw const AppFailure(FailureKind.invalidRequest);
  return id.toLowerCase();
}

List<T> jsonList<T>(Object? input, T Function(Object?) decode) {
  if (input is! List<Object?>) throw invalidResponse;
  return List.unmodifiable(input.map(decode));
}

String decimalInput(
  String input, {
  int places = 2,
  bool signed = false,
  bool positive = false,
}) {
  final text = input.trim();
  final sign = signed ? '-?' : '';
  if (!RegExp('^$sign[0-9]{1,13}(?:\\.[0-9]{1,$places})?\$').hasMatch(text) ||
      (positive && !RegExp(r'[1-9]').hasMatch(text))) {
    throw const AppFailure(FailureKind.invalidRequest);
  }
  return text;
}

// Equality normalization only: no rounding, totals, stock or credit arithmetic.
String decimalIdentity(String input) {
  final text = ServerDecimal.parse(input).text;
  final parts = text.split('.');
  var whole = parts.first.replaceFirstMapped(
    RegExp(r'^(-?)0+(?=[0-9])'),
    (match) => match.group(1) ?? '',
  );
  final fraction = parts.length == 1
      ? ''
      : parts.last.replaceFirst(RegExp(r'0+$'), '');
  if (whole == '-0' && fraction.isEmpty) whole = '0';
  return fraction.isEmpty ? whole : '$whole.$fraction';
}

void requireDecimalBinding(ServerDecimal value, Object? requested) {
  if (requested is! String ||
      decimalIdentity(value.text) != decimalIdentity(requested)) {
    throw invalidResponse;
  }
}

String textInput(String input, int max, {bool required = false}) {
  final text = input.trim();
  if (text.length > max || (required && text.isEmpty)) {
    throw const AppFailure(FailureKind.invalidRequest);
  }
  return text;
}

String? optionalText(String input, [int max = 500]) {
  final text = textInput(input, max);
  return text.isEmpty ? null : text;
}

void bindId(String actual, String expected) {
  if (actual != idPath(expected)) throw invalidResponse;
}

abstract interface class AdminInput {
  Map<String, Object?> toJson();
}

class NoInput implements AdminInput {
  const NoInput();
  @override
  Map<String, Object?> toJson() => const {};
}

class Accepted {
  const Accepted();
}
