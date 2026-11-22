import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_widgets.dart';
import '../../core/formatters.dart';
import '../auth/auth_provider.dart';
import 'account_provider.dart';

class AccountScreen extends ConsumerWidget {
  const AccountScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(authProvider.select((value) => value.key)) == null) {
      return const SizedBox.shrink();
    }
    final data = ref.watch(customerProfileQuery.provider(null));
    final refresh = ref.read(customerProfileQuery.refreshProvider(null));
    return Scaffold(
      appBar: AppBar(title: const Text('My account'), actions: [
        IconButton(
            tooltip: 'Refresh account',
            onPressed: data.isLoading ? null : refresh,
            icon: const Icon(Icons.refresh)),
        SessionLogoutButton(sessionProvider: authProvider),
      ]),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: data.when(
          skipLoadingOnReload: false,
          skipLoadingOnRefresh: false,
          data: (profile) => CustomerList(children: [
            CustomerSection(
              title: profile.name,
              icon: Icons.person_outline,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    DataField('Customer code', profile.code),
                    if (profile.businessName != null)
                      DataField('Business', profile.businessName!),
                    DataField('Account type', profile.customerType),
                    DataField('Account profile',
                        profile.isActive ? 'Active' : 'Inactive'),
                    if (profile.email != null)
                      DataField('Email', profile.email!),
                    if (profile.phone != null)
                      DataField('Phone', profile.phone!),
                    DataField('Address', profile.address ?? 'Not provided'),
                    if (profile.city != null) DataField('City', profile.city!),
                    if (profile.state != null)
                      DataField('State', profile.state!),
                    if (profile.pincode != null)
                      DataField('Postal code', profile.pincode!),
                    if (profile.gstin != null)
                      DataField('GST registration', profile.gstin!),
                  ]),
            ),
            if (!profile.isActive)
              const CustomerNotice(
                  'This customer profile is inactive. The server will determine ordering eligibility.',
                  isError: true),
            const CustomerNotice(
                'The account API does not supply a currency. Balances below are exact server values, with no currency inferred.'),
            CustomerSection(
                title: 'Your server balances',
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      DataField('Outstanding balance',
                          formatMoney(profile.outstanding, null)),
                      DataField('Advance balance',
                          formatMoney(profile.advanceBalance, null)),
                      DataField('Credit limit',
                          formatMoney(profile.creditLimit, null)),
                      DataField(
                          'Credit held', formatMoney(profile.creditHeld, null)),
                      DataField('Cash funded pending',
                          formatMoney(profile.cashFundedPending, null)),
                      DataField('Credit exposure',
                          formatMoney(profile.creditExposure, null)),
                      DataField('Available credit',
                          formatMoney(profile.availableCredit, null)),
                    ])),
            Wrap(spacing: 12, runSpacing: 12, children: [
              FilledButton.icon(
                  onPressed: () => context.go('/account/ledger'),
                  icon: const Icon(Icons.account_balance_wallet_outlined),
                  label: const Text('View ledger')),
              OutlinedButton.icon(
                  onPressed: () => context.go('/account/payments'),
                  icon: const Icon(Icons.payments_outlined),
                  label: const Text('Recorded payments')),
            ]),
            const SizedBox(height: 20),
            const Text(
                'Balances and receipts are read-only. Payment collection is handled by the business, not this app.'),
          ]),
          loading: () => const ReadLoading(),
          error: (error, _) => ReadFeedback(
              title: 'Unable to load your account.',
              message: AppFailure.safe(error).message,
              onRetry: refresh),
        ),
      ),
    );
  }
}

class LedgerScreen extends ConsumerWidget {
  const LedgerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(authProvider.select((value) => value.key)) == null) {
      return const SizedBox.shrink();
    }
    final data = ref.watch(ledgerQuery.provider(null));
    final refresh = ref.read(ledgerQuery.refreshProvider(null));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Account ledger'),
        leading: IconButton(
            tooltip: 'Back to account',
            onPressed: () => context.go('/account'),
            icon: const Icon(Icons.arrow_back)),
        actions: [
          IconButton(
              tooltip: 'Refresh ledger',
              onPressed: data.isLoading ? null : refresh,
              icon: const Icon(Icons.refresh)),
          SessionLogoutButton(sessionProvider: authProvider),
        ],
      ),
      body: RefreshIndicator(
          onRefresh: refresh,
          child: data.when(
            skipLoadingOnRefresh: false,
            skipLoadingOnReload: false,
            data: (view) => CustomerList(children: [
              Text(view.profile.name,
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 12),
              const CustomerNotice(
                  'Most recent 100 ledger entries, in server order. No balances or totals are calculated on this device.'),
              if (view.entries.isEmpty)
                const InlineReadState(title: 'No ledger entries recorded.'),
              for (final entry in view.entries)
                CustomerSection(
                    title: entry.referenceType ?? 'Ledger entry',
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          DataField('Recorded (server time)',
                              formatDateTime(entry.createdAt)),
                          DataField('Debit', formatMoney(entry.debit, null)),
                          DataField('Credit', formatMoney(entry.credit, null)),
                          DataField('Balance after entry',
                              formatMoney(entry.balanceAfter, null)),
                          if (entry.note != null)
                            DataField('Note', entry.note!),
                          if (entry.referenceId != null)
                            DataField('Reference ID', entry.referenceId!),
                          if (entry.referenceType == 'order' &&
                              entry.referenceId != null)
                            OutlinedButton(
                                onPressed: () =>
                                    context.go('/orders/${entry.referenceId}'),
                                child: const Text('View linked order')),
                        ])),
            ]),
            loading: () => const ReadLoading(),
            error: (error, _) => ReadFeedback(
                title: 'Unable to load ledger.',
                message: AppFailure.safe(error).message,
                onRetry: refresh),
          )),
    );
  }
}

class PaymentsScreen extends ConsumerWidget {
  const PaymentsScreen({this.orderId, super.key});
  final String? orderId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(authProvider.select((value) => value.key)) == null) {
      return const SizedBox.shrink();
    }
    final data = ref.watch(paymentsQuery.provider(orderId));
    final refresh = ref.read(paymentsQuery.refreshProvider(orderId));
    return Scaffold(
      appBar: AppBar(
        title: const Text('Recorded payments'),
        leading: IconButton(
            tooltip: orderId == null ? 'Back to account' : 'Back to order',
            onPressed: () =>
                context.go(orderId == null ? '/account' : '/orders/$orderId'),
            icon: const Icon(Icons.arrow_back)),
        actions: [
          IconButton(
              tooltip: 'Refresh payments',
              onPressed: data.isLoading ? null : refresh,
              icon: const Icon(Icons.refresh)),
          SessionLogoutButton(sessionProvider: authProvider),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: CustomerList(children: [
          CustomerSearch(
            key: ValueKey(orderId),
            label: 'Filter by order ID',
            initialText: orderId ?? '',
            onSearch: (value) {
              if (value.isEmpty) {
                context.go('/account/payments');
              } else if (isUuid(value)) {
                context.go('/account/payments?order_id=${value.toLowerCase()}');
              } else {
                showCustomerFailure(
                    context, const AppFailure(FailureKind.validation));
              }
            },
          ),
          const SizedBox(height: 12),
          if (orderId != null)
            TextButton(
                onPressed: () => context.go('/account/payments'),
                child: const Text('All my payments')),
          const CustomerNotice(
              'Most recent 200 receipts returned by the server. Recorded receipts are not a payment gateway or an invoice.'),
          data.when(
            skipLoadingOnRefresh: false,
            skipLoadingOnReload: false,
            data: (view) => view.receipts.isEmpty
                ? const InlineReadState(
                    title: 'No payments recorded for this view.')
                : Column(children: [
                    for (final receipt in view.receipts)
                      CustomerSection(
                          title: 'Receipt ${shortId(receipt.id)}',
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                DataField('Amount recorded',
                                    formatMoney(receipt.amount, null)),
                                DataField('Mode', receipt.mode),
                                DataField('Allocation', receipt.allocationKind),
                                DataField('Recorded (server time)',
                                    formatDateTime(receipt.createdAt)),
                                DataField('Receipt ID', receipt.id),
                                if (receipt.reference != null)
                                  DataField('Reference', receipt.reference!),
                                if (receipt.note != null)
                                  DataField('Note', receipt.note!),
                                if (receipt.orderId != null)
                                  OutlinedButton(
                                      onPressed: () => context
                                          .go('/orders/${receipt.orderId}'),
                                      child: const Text('View linked order')),
                              ])),
                  ]),
            loading: () => const SizedBox(height: 240, child: ReadLoading()),
            error: (error, _) => InlineReadState(
                title: 'Unable to load payments.',
                error: error,
                onRetry: refresh),
          ),
        ]),
      ),
    );
  }
}
