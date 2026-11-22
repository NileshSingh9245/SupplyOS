import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';
import '../auth/auth_provider.dart';
import 'account.dart';

final customerProfileQuery = SessionQuery<CustomerProfile, void>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) async => CustomerProfile.parseOwn(
      await session.get('/customers',
          scope: scope,
          queryParameters: {'page': 1, 'page_size': 50},
          cancelToken: token)),
);

final ledgerQuery = SessionQuery<LedgerView, void>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) async {
    final profile = CustomerProfile.parseOwn(await session.get('/customers',
        scope: scope,
        queryParameters: {'page': 1, 'page_size': 50},
        cancelToken: token));
    final rows = serverList(
        await session.get('/customers/${profile.id.toLowerCase()}/ledger',
            scope: scope, queryParameters: {'limit': 100}, cancelToken: token),
        LedgerEntry.fromJson);
    requireUniqueIds(rows, (row) => row.id);
    return LedgerView(profile, rows);
  },
);

final paymentsQuery = SessionQuery<PaymentsView, String?>(
  sessionProvider: authProvider,
  load: (session, scope, orderId, token) async {
    if (orderId != null && !isUuid(orderId)) throw invalidResponse;
    final profile = CustomerProfile.parseOwn(await session.get('/customers',
        scope: scope,
        queryParameters: {'page': 1, 'page_size': 50},
        cancelToken: token));
    final rows = serverList(
        await session.get('/payments',
            scope: scope,
            queryParameters: {
              'customer_id': profile.id.toLowerCase(),
              if (orderId != null) 'order_id': orderId.toLowerCase(),
            },
            cancelToken: token),
        PaymentReceipt.fromJson);
    requireUniqueIds(rows, (row) => row.id);
    for (final row in rows) {
      if (row.customerId.toLowerCase() != profile.id.toLowerCase() ||
          (orderId != null &&
              row.orderId?.toLowerCase() != orderId.toLowerCase())) {
        throw invalidResponse;
      }
    }
    return PaymentsView(profile, rows);
  },
);
