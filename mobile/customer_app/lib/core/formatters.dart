import 'package:supplyos_core/supplyos_core.dart';

String formatMoney(ServerDecimal value, String? currencyCode) =>
    currencyCode == null
        ? '${value.text} (currency not recorded)'
        : '$currencyCode ${value.text}';

String formatDate(ServerDate? value) => value?.text ?? 'Not scheduled';

String formatDateTime(ServerTimestamp? value) => value?.text ?? 'Not recorded';
