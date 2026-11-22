import 'package:supplyos_core/supplyos_core.dart';

String formatINR(ServerDecimal value) => 'INR ${value.text}';

String formatDate(ServerDate? value) => value?.text ?? 'Not scheduled';

String formatDateTime(ServerTimestamp? value) => value?.text ?? 'Not recorded';
