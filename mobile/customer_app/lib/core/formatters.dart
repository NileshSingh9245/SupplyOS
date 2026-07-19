import 'package:intl/intl.dart';

String formatINR(dynamic value, {int decimals = 2, String symbol = '₹'}) {
  if (value == null) return '${symbol}0.00';
  final n = value is num ? value.toDouble() : double.tryParse(value.toString()) ?? 0.0;
  final f = NumberFormat.currency(
    locale: 'en_IN', symbol: symbol, decimalDigits: decimals,
  );
  return f.format(n);
}

String formatDate(String? iso) {
  if (iso == null) return '—';
  try {
    final dt = DateTime.parse(iso).toLocal();
    return DateFormat('d MMM y').format(dt);
  } catch (_) {
    return iso;
  }
}

String formatDateTime(String? iso) {
  if (iso == null) return '—';
  try {
    final dt = DateTime.parse(iso).toLocal();
    return DateFormat('d MMM y · HH:mm').format(dt);
  } catch (_) {
    return iso;
  }
}
