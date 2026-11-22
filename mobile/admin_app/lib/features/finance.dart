import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../core/contracts.dart';
import '../core/forms.dart';
import '../core/intents.dart';
import '../core/navigation.dart';
import '../core/providers.dart';
import '../core/widgets.dart';
import 'customers.dart';
import 'orders.dart';

const receiptModes = {'cash', 'upi', 'bank_transfer', 'credit'};

class PaymentRecord {
  PaymentRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    customerId = json.uuid('customer_id');
    orderId = json.optionalUuid('order_id');
    amount = json.decimal('amount');
    mode = json.string('mode');
    kind = json.string('allocation_kind');
    reference = json.optionalString('reference');
    note = json.optionalString('note');
    createdAt = json.timestamp('created_at');
    if (!receiptModes.contains(mode) ||
        !const {
          'order_payment',
          'unallocated_advance',
          'credit_note',
        }.contains(kind) ||
        kind !=
            (orderId != null
                ? 'order_payment'
                : mode == 'credit'
                ? 'credit_note'
                : 'unallocated_advance') ||
        (mode == 'credit' && orderId != null)) {
      throw invalidResponse;
    }
  }
  late final String id, customerId, mode, kind;
  late final String? orderId, reference, note;
  late final ServerDecimal amount;
  late final ServerTimestamp createdAt;
}

final paymentsQuery = SessionQuery<List<PaymentRecord>, String?>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) {
    requireRoles(scope, financeWriters);
    return AdminRepository(session).read('/payments', scope, token, (raw) {
      final rows = jsonList(raw, PaymentRecord.new);
      for (final row in rows) {
        if (id != null) bindId(row.customerId, id);
      }
      return rows;
    }, parameters: {if (id != null) 'customer_id': idPath(id)});
  },
);

class PaymentInput implements AdminInput {
  const PaymentInput({
    required this.customerId,
    required this.amount,
    required this.mode,
    this.orderId,
    this.reference = '',
    this.note = '',
  });
  final String customerId, amount, mode, reference, note;
  final String? orderId;
  @override
  Map<String, Object?> toJson() {
    if (!receiptModes.contains(mode) ||
        (mode == 'credit' && orderId != null && orderId != '')) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
    return {
      'customer_id': idPath(customerId),
      'order_id': orderId == null || orderId == '' ? null : idPath(orderId!),
      'amount': decimalInput(amount, positive: true),
      'mode': mode,
      'reference': optionalText(reference, 120),
      'note': optionalText(note),
    };
  }
}

final paymentCommand = AdminCommand<PaymentInput, PaymentRecord>(
  slot: 'payment:create',
  title: 'Record manual receipt',
  route: '/finance',
  roles: financeWriters,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/payments',
    expectedStatus: 201,
    supportsIdempotency: true,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = PaymentRecord(raw);
      final body = original.body!;
      if (value.customerId != body['customer_id'] ||
          value.orderId != body['order_id'] ||
          value.mode != body['mode'] ||
          value.reference != body['reference'] ||
          value.note != body['note']) {
        throw invalidResponse;
      }
      requireDecimalBinding(value.amount, body['amount']);
      return value;
    },
  ),
);

class FinanceScreen extends ConsumerStatefulWidget {
  const FinanceScreen({super.key});
  @override
  ConsumerState<FinanceScreen> createState() => _FinanceScreenState();
}

class _FinanceScreenState extends ConsumerState<FinanceScreen> {
  String? customerId, customerLabel;
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Manual ledger allocation / server due',
    title: 'Finance',
    actions: [
      OutlinedButton(
        onPressed: ref.read(paymentsQuery.refreshProvider(customerId)),
        child: const Text('Refresh receipts'),
      ),
    ],
    children: [
      const CapabilityNotice(
        'Manual receipts are real server ledger operations, not gateway settlement. No amount, balance, due or stock is calculated in Dart. Invoices/statements, refunds, full accounting and durable offline reconciliation remain unavailable.',
      ),
      IntentForm(
        command: paymentCommand,
        fields: [
          AdminField(
            'customer_id',
            'Receipt customer',
            kind: FieldKind.lookup,
            required: true,
            pick: pickCustomer,
            resets: const ['order_id'],
          ),
          const AdminField(
            'mode',
            'Receipt mode',
            kind: FieldKind.choice,
            initial: 'cash',
            required: true,
            choices: {
              'cash': 'Cash',
              'upi': 'UPI (manual confirmation)',
              'bank_transfer': 'Bank transfer (manual)',
              'credit': 'Credit note (not collected funds)',
            },
          ),
          const AdminField(
            'amount',
            'Receipt amount',
            kind: FieldKind.decimal,
            required: true,
          ),
          const AdminField('reference', 'Payment reference', maxLength: 120),
          const AdminField(
            'note',
            'Receipt note',
            kind: FieldKind.multiline,
            maxLength: 500,
          ),
        ],
        seed: const {'order_id': ''},
        input: (v) => PaymentInput(
          customerId: v.text('customer_id'),
          amount: v.text('amount'),
          mode: v.text('mode'),
          orderId: v.text('mode') == 'credit' ? null : v.text('order_id'),
          reference: v.text('reference'),
          note: v.text('note'),
        ),
        extra: (context, ref, form) {
          final id = form.values.text('customer_id');
          final orderId = form.values.text('order_id');
          final credit = form.values.text('mode') == 'credit';
          if (id.isEmpty) {
            return const EmptyNotice(
              'Choose a customer to view current server balances and an optional order allocation.',
            );
          }
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              QueryPanel(
                query: customerQuery,
                argument: id,
                builder: (customer) => RecordCard(
                  title: customer.name,
                  label: customer.code,
                  lines: customer.balances,
                ),
              ),
              const SizedBox(height: 16),
              if (credit)
                const CapabilityNotice(
                  'Credit notes adjust the customer account and do not fund an order.',
                )
              else ...[
                OutlinedButton.icon(
                  onPressed: form.locked
                      ? null
                      : () async {
                          final order = await pickOrder(context, id);
                          if (order != null && context.mounted) {
                            form.set('order_id', order.id);
                          }
                        },
                  icon: const Icon(Icons.receipt_long),
                  label: const Text('Choose order allocation (optional)'),
                ),
                if (orderId.isNotEmpty)
                  QueryPanel(
                    query: orderQuery,
                    argument: orderId,
                    builder: (order) {
                      if (order.customerId != id) {
                        return const EmptyNotice(
                          'Choose an order belonging to the selected customer.',
                        );
                      }
                      return RecordCard(
                        title: order.number,
                        status: order.status,
                        lines: order.funding,
                        actions: [
                          OutlinedButton(
                            onPressed: form.locked
                                ? null
                                : () => form.set('amount', order.due.text),
                            child: const Text('Use exact server amount due'),
                          ),
                          TextButton(
                            onPressed: form.locked
                                ? null
                                : () => form.set('order_id', ''),
                            child: const Text(
                              'Use unallocated advance instead',
                            ),
                          ),
                        ],
                      );
                    },
                  ),
                if (orderId.isEmpty)
                  const EmptyNotice(
                    'No order selected: collected funds are recorded as an unallocated customer advance.',
                  ),
              ],
              const SizedBox(height: 16),
            ],
          );
        },
        onSaved: (payment) {
          ref.invalidate(paymentsQuery.provider);
          ref.invalidate(customerQuery.provider);
          ref.invalidate(ledgerQuery.provider);
          ref.invalidate(orderQuery.provider);
          ref.invalidate(ordersQuery.provider);
        },
      ),
      const SizedBox(height: 16),
      OutlinedButton.icon(
        onPressed: () async {
          final picked = await pickCustomer(context, ref);
          if (picked != null && mounted) {
            setState(() {
              customerId = picked.id;
              customerLabel = picked.label;
            });
          }
        },
        icon: const Icon(Icons.person_search),
        label: Text(customerLabel ?? 'Filter receipts by customer'),
      ),
      if (customerId != null)
        TextButton(
          onPressed: () => setState(() {
            customerId = null;
            customerLabel = null;
          }),
          child: const Text('All customer receipts'),
        ),
      QueryPanel(
        query: paymentsQuery,
        argument: customerId,
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty)
              const EmptyNotice('No receipts were returned for this filter.'),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 14),
                child: RecordCard(
                  title: row.kind.replaceAll('_', ' '),
                  label: row.createdAt.text,
                  status: row.mode,
                  lines: {
                    'Amount (server)': row.amount.text,
                    'Reference': row.reference ?? 'No reference',
                    'Note': row.note ?? 'No note',
                  },
                  actions: [
                    recordLink(
                      context,
                      '/customers/${row.customerId}',
                      'Customer ledger',
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    ],
  );
}
