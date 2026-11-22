import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../core/contracts.dart';
import '../core/forms.dart';
import '../core/intents.dart';
import '../core/navigation.dart';
import '../core/providers.dart';
import '../core/widgets.dart';
import 'customers.dart';
import 'orders.dart';
import 'staff.dart';

bool _privateProof(String? value, String deliveryId) {
  if (value == null) return false;
  final uri = Uri.tryParse(value);
  final match = uri == null
      ? null
      : RegExp(
          '^/(?:api/(?:v1/)?)?deliveries/${idPath(deliveryId)}/proofs/([0-9a-fA-F-]{36})(?:/content)?\$',
        ).firstMatch(uri.path);
  if (uri == null ||
      uri.hasScheme ||
      uri.hasAuthority ||
      uri.hasQuery ||
      uri.hasFragment ||
      match == null ||
      !isUuid(match.group(1)!)) {
    throw invalidResponse;
  }
  return true;
}

class DeliveryRecord {
  DeliveryRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    orderId = json.uuid('order_id');
    partnerId = json.optionalUuid('partner_id');
    date = json.optionalDate('scheduled_date');
    priority = json.integer('priority', minimum: 1, maximum: 10);
    verified = json.boolean('otp_verified');
    hasSignature = _privateProof(json.optionalString('signature_url'), id);
    hasPhoto = _privateProof(json.optionalString('proof_photo_url'), id);
    cash = json.decimal('cash_collected');
    upi = json.decimal('upi_collected');
    started = json.optionalTimestamp('started_at');
    completed = json.optionalTimestamp('completed_at');
  }
  late final String id, orderId;
  late final String? partnerId;
  late final ServerDate? date;
  late final int priority;
  late final bool verified, hasSignature, hasPhoto;
  late final ServerDecimal cash, upi;
  late final ServerTimestamp? started, completed;
}

final deliveriesQuery = SessionQuery<List<DeliveryRecord>, String>(
  sessionProvider: authProvider,
  load: (session, scope, date, token) => AdminRepository(session).read(
    '/deliveries',
    scope,
    token,
    (raw) {
      final rows = jsonList(raw, DeliveryRecord.new);
      if (date.isNotEmpty) {
        for (final row in rows) {
          if (row.date?.text != date) throw invalidResponse;
        }
      }
      return rows;
    },
    parameters: {
      if (date.isNotEmpty) 'scheduled_date': ServerDate.parse(date).text,
    },
  ),
);

class DeliveryAssignmentInput implements AdminInput {
  const DeliveryAssignmentInput(this.partnerId, this.date, this.priority);
  final String partnerId, date;
  final int priority;
  @override
  Map<String, Object?> toJson() {
    if (priority < 1 || priority > 10) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
    return {
      'partner_id': idPath(partnerId),
      'scheduled_date': date.isEmpty ? null : ServerDate.parse(date).text,
      'priority': priority,
    };
  }
}

AdminCommand<DeliveryAssignmentInput, DeliveryRecord> assignDeliveryCommand(
  DeliveryRecord delivery,
) => AdminCommand(
  slot: 'delivery:${delivery.id}:assign',
  group: 'delivery:${delivery.id}',
  title: 'Assign delivery partner',
  route: '/deliveries/${delivery.id}',
  roles: const {ownerRole},
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/deliveries/${idPath(delivery.id)}/assign',
    expectedStatus: 200,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = DeliveryRecord(raw);
      bindId(value.id, delivery.id);
      bindId(value.orderId, delivery.orderId);
      if (value.partnerId != original.body!['partner_id'] ||
          value.priority != original.body!['priority'] ||
          (original.body!['scheduled_date'] != null &&
              value.date?.text != original.body!['scheduled_date'])) {
        throw invalidResponse;
      }
      return value;
    },
  ),
);
AdminCommand<NoInput, DeliveryRecord> startDeliveryCommand(
  DeliveryRecord delivery,
) => AdminCommand(
  slot: 'delivery:${delivery.id}:start',
  group: 'delivery:${delivery.id}',
  title: 'Start delivery',
  route: '/deliveries/${delivery.id}',
  roles: operators,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/deliveries/${idPath(delivery.id)}/start',
    expectedStatus: 200,
    encode: (_) => null,
    decode: (raw, _) {
      final value = DeliveryRecord(raw);
      bindId(value.id, delivery.id);
      bindId(value.orderId, delivery.orderId);
      if (value.started == null || value.completed != null) {
        throw invalidResponse;
      }
      return value;
    },
  ),
);

class DeliveriesScreen extends ConsumerStatefulWidget {
  const DeliveriesScreen({this.orderId, super.key});
  final String? orderId;
  @override
  ConsumerState<DeliveriesScreen> createState() => _DeliveriesScreenState();
}

class _DeliveriesScreenState extends ConsumerState<DeliveriesScreen> {
  String date = '';
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Dispatch / assignment / private outcome metadata',
    title: 'Deliveries',
    actions: [
      OutlinedButton(
        onPressed: ref.read(deliveriesQuery.refreshProvider(date)),
        child: const Text('Refresh deliveries'),
      ),
    ],
    children: [
      TextFormField(
        decoration: const InputDecoration(
          labelText: 'Scheduled date filter',
          helperText: 'YYYY-MM-DD, blank for all dates',
        ),
        textInputAction: TextInputAction.search,
        onFieldSubmitted: (value) {
          try {
            if (value.trim().isNotEmpty) ServerDate.parse(value.trim());
            setState(() => date = value.trim());
          } on AppFailure {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Use a valid YYYY-MM-DD date.')),
            );
          }
        },
      ),
      QueryPanel(
        query: deliveriesQuery,
        argument: date,
        builder: (result) {
          final rows = widget.orderId == null
              ? result
              : result
                    .where((delivery) => delivery.orderId == widget.orderId)
                    .toList();
          return Column(
            children: [
              if (rows.isEmpty)
                const EmptyNotice(
                  'No deliveries match this date/order context.',
                ),
              for (final row in rows)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: QueryPanel(
                    query: orderQuery,
                    argument: row.orderId,
                    builder: (order) => RecordCard(
                      title: order.number,
                      status: row.completed != null
                          ? 'completed'
                          : row.started != null
                          ? 'started'
                          : 'scheduled',
                      lines: {
                        'Scheduled date': row.date?.text ?? 'Not scheduled',
                        'Priority': '${row.priority}',
                        'Order status': order.status,
                        'Server due': order.due.text,
                      },
                      onTap: () => context.go('/deliveries/${row.id}'),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
      const CapabilityNotice(
        'Start and owner assignment are real JSON operations. OTP/challenge delivery, QR verification, private signature/photo transport, completion and payment-linked proof finalization require dedicated contracts; no completion button substitutes for them.',
      ),
    ],
  );
}

class DeliveryDetailScreen extends ConsumerWidget {
  const DeliveryDetailScreen(this.id, {super.key});
  final String id;
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Current delivery and order context',
    title: 'Delivery detail',
    actions: [
      recordLink(context, '/deliveries', 'Deliveries'),
      OutlinedButton(
        onPressed: ref.read(deliveriesQuery.refreshProvider('')),
        child: const Text('Refresh'),
      ),
    ],
    children: [
      QueryPanel(
        query: deliveriesQuery,
        argument: '',
        builder: (rows) {
          final delivery = rows.where((row) => row.id == id).firstOrNull;
          if (delivery == null) {
            return const EmptyNotice('Delivery not found in this account.');
          }
          return QueryPanel(
            query: orderQuery,
            argument: delivery.orderId,
            builder: (order) => Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                RecordCard(
                  title: order.number,
                  status: order.status,
                  lines: {
                    'Scheduled date': delivery.date?.text ?? 'Not set',
                    'Priority': '${delivery.priority}',
                    'Delivery address': order.address ?? 'Not set',
                    'Server order due': order.due.text,
                    'Recipient verification': delivery.verified
                        ? 'Recorded'
                        : 'Pending',
                    'Signature receipt': delivery.hasSignature
                        ? 'Recorded privately'
                        : 'Not recorded',
                    'Photo receipt': delivery.hasPhoto
                        ? 'Recorded privately'
                        : 'Not recorded',
                    'Cash recorded': delivery.cash.text,
                    'UPI recorded': delivery.upi.text,
                    'Started': delivery.started?.text ?? 'Not started',
                    'Completed': delivery.completed?.text ?? 'Not completed',
                  },
                ),
                const SizedBox(height: 16),
                QueryPanel(
                  query: customerQuery,
                  argument: order.customerId,
                  builder: (customer) => RecordCard(
                    title: customer.name,
                    label: customer.code,
                    lines: {
                      'Contact phone': customer.phone ?? 'Not set',
                      'Address': customer.address ?? 'Not set',
                    },
                  ),
                ),
                const SizedBox(height: 16),
                for (final line in order.lines)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: RecordCard(
                      title: line.name,
                      label: line.sku,
                      lines: {'Quantity': line.quantity.text},
                    ),
                  ),
                if (order.status == 'out_for_delivery' &&
                    delivery.completed == null &&
                    delivery.started == null)
                  IntentForm(
                    command: startDeliveryCommand(delivery),
                    fields: const [],
                    input: (_) => const NoInput(),
                    onSaved: (_) =>
                        ref.read(deliveriesQuery.refreshProvider(''))(),
                  ),
                if (order.status == 'out_for_delivery' &&
                    delivery.completed == null &&
                    ref.watch(authProvider).key?.role == ownerRole)
                  Padding(
                    padding: const EdgeInsets.only(top: 24),
                    child: IntentForm(
                      command: assignDeliveryCommand(delivery),
                      fields: [
                        AdminField(
                          'partner_id',
                          'Active delivery partner',
                          initial: delivery.partnerId ?? '',
                          kind: FieldKind.lookup,
                          required: true,
                          pick: (context, _) => pickPartner(context),
                        ),
                        AdminField(
                          'scheduled_date',
                          'Scheduled date',
                          initial: delivery.date?.text ?? '',
                          kind: FieldKind.date,
                          maxLength: 10,
                        ),
                        AdminField(
                          'priority',
                          'Priority (1 to 10)',
                          initial: '${delivery.priority}',
                          kind: FieldKind.integer,
                          required: true,
                        ),
                      ],
                      input: (v) => DeliveryAssignmentInput(
                        v.text('partner_id'),
                        v.text('scheduled_date'),
                        v.integer('priority'),
                      ),
                      onSaved: (_) =>
                          ref.read(deliveriesQuery.refreshProvider(''))(),
                    ),
                  ),
                if (ref.watch(authProvider).key?.role == managerRole)
                  const CapabilityNotice(
                    'The current staff candidate API is owner-only. Manager assignment selection is held until a dedicated authorized partner-candidate API exists; no raw partner UUID entry bypasses that boundary.',
                  ),
              ],
            ),
          );
        },
      ),
      const CapabilityNotice(
        'Private proof links are validated but neither displayed nor fetched as generic JSON. OTP, password/account, multipart, binary evidence, collections/completion and cross-device/offline synchronization remain separate work.',
      ),
    ],
  );
}
