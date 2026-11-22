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
import 'catalog.dart';
import 'customers.dart';
import 'locations.dart';

const orderStatuses = {
  'pending',
  'confirmed',
  'reserved',
  'picked',
  'packed',
  'out_for_delivery',
  'delivered',
  'paid',
  'completed',
  'cancelled',
};
const liveOrderStatuses = {
  'pending',
  'confirmed',
  'reserved',
  'picked',
  'packed',
  'out_for_delivery',
};
const actionStatuses = {
  'confirm': 'confirmed',
  'reserve': 'reserved',
  'pick': 'picked',
  'pack': 'packed',
  'dispatch': 'out_for_delivery',
  'cancel': 'cancelled',
};
List<String> orderActions(String status) => [
  if (status == 'pending') 'confirm',
  if (status == 'confirmed') 'reserve',
  if (status == 'reserved') 'pick',
  if (status == 'picked') 'pack',
  if (status == 'packed') 'dispatch',
  if (liveOrderStatuses.contains(status)) 'cancel',
];

class OrderLineRecord {
  OrderLineRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    productId = json.uuid('product_id');
    sku = json.string('product_sku');
    name = json.string('product_name');
    quantity = json.decimal('quantity');
    price = json.decimal('unit_price');
    gst = json.decimal('gst_rate');
    subtotal = json.decimal('line_subtotal');
    tax = json.decimal('line_tax');
    total = json.decimal('line_total');
  }
  late final String id, productId, sku, name;
  late final ServerDecimal quantity, price, gst, subtotal, tax, total;
}

class OrderRecord {
  OrderRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    number = json.string('order_number');
    customerId = json.uuid('customer_id');
    warehouseId = json.uuid('warehouse_id');
    status = json.string('status');
    if (!orderStatuses.contains(status)) throw invalidResponse;
    channel = json.string('channel');
    currency = json.optionalString('currency_code');
    if (currency != null && !RegExp(r'^[A-Z]{3}$').hasMatch(currency!)) {
      throw invalidResponse;
    }
    paymentMode = json.string('payment_mode');
    paymentStatus = json.string('payment_status');
    if (!const {'cash', 'credit'}.contains(paymentMode) ||
        !const {'unpaid', 'partial', 'paid'}.contains(paymentStatus)) {
      throw invalidResponse;
    }
    subtotal = json.decimal('subtotal');
    tax = json.decimal('tax_total');
    discount = json.decimal('discount_total');
    total = json.decimal('grand_total');
    paid = json.decimal('amount_paid');
    due = json.decimal('amount_due');
    hold = json.decimal('credit_hold_amount');
    scheduled = json.optionalDate('scheduled_delivery_date');
    address = json.optionalString('delivery_address');
    notes = json.optionalString('notes');
    createdAt = json.timestamp('created_at');
    confirmedAt = json.optionalTimestamp('confirmed_at');
    deliveredAt = json.optionalTimestamp('delivered_at');
    lines = json.list('items', OrderLineRecord.new);
    if (lines.map((line) => line.id).toSet().length != lines.length) {
      throw invalidResponse;
    }
  }
  late final String id,
      number,
      customerId,
      warehouseId,
      status,
      channel,
      paymentMode,
      paymentStatus;
  late final String? address, notes, currency;
  late final ServerDate? scheduled;
  late final ServerTimestamp createdAt;
  late final ServerTimestamp? confirmedAt, deliveredAt;
  late final ServerDecimal subtotal, tax, discount, total, paid, due, hold;
  late final List<OrderLineRecord> lines;
  Map<String, String> get funding => {
    'Document currency': currency ?? 'Unknown legacy currency',
    'Grand total': total.text,
    'Allocated receipts': paid.text,
    'Server amount due': due.text,
    'Credit hold': hold.text,
    'Payment mode': paymentMode,
    'Payment status': paymentStatus,
  };
}

class OrderHistoryRecord {
  OrderHistoryRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    from = json.optionalString('from_status');
    to = json.string('to_status');
    if (!orderStatuses.contains(to) ||
        (from != null && !orderStatuses.contains(from))) {
      throw invalidResponse;
    }
    actor = json.optionalUuid('actor_id');
    note = json.optionalString('note');
    createdAt = json.timestamp('created_at');
  }
  late final String id, to;
  late final String? from, actor, note;
  late final ServerTimestamp createdAt;
}

class OrderStats {
  OrderStats(Object? raw) {
    final json = JsonObject(raw);
    total = json.integer('total_orders');
    pending = json.integer('pending');
    confirmed = json.integer('confirmed');
    reserved = json.integer('reserved');
    out = json.integer('out_for_delivery');
    delivered = json.integer('delivered_today');
    revenue = json.decimal('revenue_today');
  }
  late final int total, pending, confirmed, reserved, out, delivered;
  late final ServerDecimal revenue;
  Map<String, String> get counters => {
    'All orders': '$total',
    'Pending': '$pending',
    'Confirmed': '$confirmed',
    'Reserved': '$reserved',
    'Out for delivery': '$out',
    'Delivered today': '$delivered',
    'Revenue today (server)': revenue.text,
  };
}

typedef OrderFilter = ({int page, String status, String? customerId});
final ordersQuery = SessionQuery<Paginated<OrderRecord>, OrderFilter>(
  sessionProvider: authProvider,
  load: (session, scope, arg, token) => AdminRepository(session).read(
    '/orders',
    scope,
    token,
    (raw) {
      final page = Paginated.fromJson(raw, OrderRecord.new);
      page.requirePage(arg.page, 50);
      for (final order in page.items) {
        if (arg.customerId != null) bindId(order.customerId, arg.customerId!);
        if (arg.status.isNotEmpty && order.status != arg.status) {
          throw invalidResponse;
        }
      }
      return page;
    },
    parameters: {
      'page': arg.page,
      'page_size': 50,
      if (arg.status.isNotEmpty) 'status': arg.status,
      if (arg.customerId != null) 'customer_id': idPath(arg.customerId!),
    },
  ),
);
final orderQuery = SessionQuery<OrderRecord, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) =>
      AdminRepository(session)
          .read('/orders/${idPath(id)}', scope, token, (raw) {
            final value = OrderRecord(raw);
            bindId(value.id, id);
            return value;
          }),
);
final orderHistoryQuery = SessionQuery<List<OrderHistoryRecord>, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) => AdminRepository(session).read(
    '/orders/${idPath(id)}/history',
    scope,
    token,
    (raw) => jsonList(raw, OrderHistoryRecord.new),
  ),
);
final orderStatsQuery = SessionQuery<OrderStats, int>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) =>
      AdminRepository(session)
          .read('/orders/stats', scope, token, OrderStats.new),
);

class OrderLineInput {
  const OrderLineInput(this.productId, this.quantity);
  final String productId, quantity;
  Map<String, Object?> toJson() => {
    'product_id': idPath(productId),
    'quantity': decimalInput(quantity, places: 3, positive: true),
  };
}

class OrderInput implements AdminInput {
  OrderInput({
    required this.customerId,
    required this.warehouseId,
    required List<OrderLineInput> lines,
    this.paymentMode,
    this.scheduled,
    this.address = '',
    this.notes = '',
  }) : lines = List.unmodifiable(lines);
  final String customerId, warehouseId, address, notes;
  final String? paymentMode, scheduled;
  final List<OrderLineInput> lines;
  @override
  Map<String, Object?> toJson() {
    if (lines.isEmpty ||
        lines.length > 200 ||
        lines.map((line) => line.productId).toSet().length != lines.length ||
        (paymentMode != null &&
            paymentMode != '' &&
            !const {'cash', 'credit'}.contains(paymentMode))) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
    return {
      'customer_id': idPath(customerId),
      'warehouse_id': idPath(warehouseId),
      'channel': 'admin',
      'payment_mode': paymentMode == null || paymentMode == ''
          ? null
          : paymentMode,
      'scheduled_delivery_date': scheduled == null || scheduled == ''
          ? null
          : ServerDate.parse(scheduled).text,
      'delivery_address': optionalText(address),
      'notes': optionalText(notes),
      'items': [for (final line in lines) line.toJson()],
    };
  }
}

final createOrderCommand = AdminCommand<OrderInput, OrderRecord>(
  slot: 'order:create',
  title: 'Create pending order',
  route: '/orders/new',
  roles: operators,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/orders',
    expectedStatus: 201,
    supportsIdempotency: true,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = OrderRecord(raw);
      final body = original.body!;
      if (value.customerId != body['customer_id'] ||
          value.warehouseId != body['warehouse_id'] ||
          value.channel != body['channel'] ||
          value.status != 'pending' ||
          value.scheduled?.text != body['scheduled_delivery_date'] ||
          value.address != body['delivery_address'] ||
          value.notes != body['notes'] ||
          (body['payment_mode'] != null &&
              value.paymentMode != body['payment_mode'])) {
        throw invalidResponse;
      }
      final expected = (body['items']! as List).map(JsonObject.new).toList();
      if (value.lines.length != expected.length) throw invalidResponse;
      for (final item in expected) {
        final line = value.lines
            .where((line) => line.productId == item.uuid('product_id'))
            .firstOrNull;
        if (line == null) throw invalidResponse;
        requireDecimalBinding(line.quantity, item.value('quantity'));
      }
      return value;
    },
  ),
);

class OrderActionInput implements AdminInput {
  const OrderActionInput(this.note);
  final String note;
  @override
  Map<String, Object?> toJson() => {'note': optionalText(note)};
}

AdminCommand<OrderActionInput, OrderRecord> orderActionCommand(
  String orderId,
  String action,
) {
  if (!actionStatuses.containsKey(action)) {
    throw const AppFailure(FailureKind.invalidRequest);
  }
  return AdminCommand(
    slot: 'order:$orderId:$action',
    group: 'order:$orderId',
    title: '${action[0].toUpperCase()}${action.substring(1)} order',
    route: '/orders/$orderId',
    roles: operators,
    endpoint: JsonMutationEndpoint(
      method: MutationMethod.post,
      path: '/orders/${idPath(orderId)}/$action',
      expectedStatus: 200,
      encode: (input) =>
          action == 'confirm' || action == 'reserve' ? null : input.toJson(),
      decode: (raw, original) {
        final value = OrderRecord(raw);
        bindId(value.id, orderId);
        if (value.status != actionStatuses[action]) throw invalidResponse;
        return value;
      },
    ),
  );
}

class OrdersScreen extends ConsumerStatefulWidget {
  const OrdersScreen({super.key});
  @override
  ConsumerState<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends ConsumerState<OrdersScreen> {
  int page = 1;
  String status = '';
  String? customerId, customerLabel;
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Manual order operations / server authority',
    title: 'Orders',
    actions: [
      recordLink(context, '/orders/new', 'Create order'),
      OutlinedButton(
        onPressed: ref.read(
          ordersQuery.refreshProvider((
            page: page,
            status: status,
            customerId: customerId,
          )),
        ),
        child: const Text('Refresh'),
      ),
    ],
    children: [
      DropdownButtonFormField<String>(
        initialValue: status,
        isExpanded: true,
        itemHeight: null,
        decoration: const InputDecoration(labelText: 'Order status'),
        items: [
          const DropdownMenuItem(value: '', child: Text('All statuses')),
          for (final value in orderStatuses)
            DropdownMenuItem(value: value, child: Text(statusLabel(value))),
        ],
        onChanged: (value) => setState(() {
          status = value ?? '';
          page = 1;
        }),
      ),
      OutlinedButton.icon(
        onPressed: () async {
          final choice = await pickCustomer(context, ref);
          if (choice != null && mounted) {
            setState(() {
              customerId = choice.id;
              customerLabel = choice.label;
              page = 1;
            });
          }
        },
        icon: const Icon(Icons.person_search),
        label: Text(customerLabel ?? 'Filter by customer'),
      ),
      if (customerId != null)
        TextButton(
          onPressed: () => setState(() {
            customerId = null;
            customerLabel = null;
            page = 1;
          }),
          child: const Text('Clear customer filter'),
        ),
      QueryPanel(
        query: ordersQuery,
        argument: (page: page, status: status, customerId: customerId),
        builder: (result) => Column(
          children: [
            if (result.items.isEmpty)
              const EmptyNotice('No orders match these filters.'),
            for (final order in result.items)
              Padding(
                padding: const EdgeInsets.only(bottom: 14),
                child: RecordCard(
                  title: order.number,
                  status: order.status,
                  lines: {
                    'Created': order.createdAt.text,
                    'Grand total': order.total.text,
                    'Server due': order.due.text,
                    'Payment': '${order.paymentMode} / ${order.paymentStatus}',
                  },
                  onTap: () => context.go('/orders/${order.id}'),
                ),
              ),
            AdminPageControls(
              page: result.page,
              total: result.total,
              hasNext: result.hasNext,
              onPage: (value) => setState(() => page = value),
            ),
          ],
        ),
      ),
    ],
  );
}

class OrderDetailScreen extends ConsumerWidget {
  const OrderDetailScreen(this.id, {super.key});
  final String id;
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Historical snapshot / ordered server history',
    title: 'Order detail',
    actions: [
      recordLink(context, '/orders', 'All orders'),
      OutlinedButton(
        onPressed: () {
          ref.read(orderQuery.refreshProvider(id))();
          ref.read(orderHistoryQuery.refreshProvider(id))();
        },
        child: const Text('Refresh'),
      ),
    ],
    children: [
      QueryPanel(
        query: orderQuery,
        argument: id,
        builder: (order) => Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            RecordCard(
              title: order.number,
              status: order.status,
              lines: {
                ...order.funding,
                'Scheduled date': order.scheduled?.text ?? 'Not set',
                'Delivery address': order.address ?? 'Not set',
                'Notes': order.notes ?? 'No note',
              },
            ),
            const SizedBox(height: 16),
            QueryPanel(
              query: customerQuery,
              argument: order.customerId,
              builder: (customer) => RecordCard(
                title: customer.name,
                label: customer.code,
                lines: {'Phone': customer.phone ?? 'Not set'},
              ),
            ),
            const SizedBox(height: 16),
            for (final line in order.lines)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: line.name,
                  label: line.sku,
                  lines: {
                    'Quantity': line.quantity.text,
                    'Snapshot unit price': line.price.text,
                    'Snapshot GST rate': line.gst.text,
                    'Line tax': line.tax.text,
                    'Line total': line.total.text,
                  },
                ),
              ),
            if (const {
              'out_for_delivery',
              'delivered',
              'paid',
              'completed',
            }.contains(order.status))
              recordLink(
                context,
                '/deliveries?order_id=$id',
                'Delivery context',
              ),
            for (final action in orderActions(order.status))
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: IntentForm(
                  key: ValueKey('action:$id:$action'),
                  command: orderActionCommand(id, action),
                  fields: action == 'confirm' || action == 'reserve'
                      ? const []
                      : [
                          AdminField(
                            'note',
                            '${action == 'cancel' ? 'Cancellation' : 'Action'} note',
                            kind: FieldKind.multiline,
                            maxLength: 500,
                          ),
                        ],
                  input: (v) => OrderActionInput(v.text('note')),
                  onSaved: (_) {
                    ref.invalidate(orderQuery.provider);
                    ref.invalidate(ordersQuery.provider);
                    ref.invalidate(orderHistoryQuery.provider);
                    ref.invalidate(orderStatsQuery.provider);
                    ref.invalidate(inventoryQuery.provider);
                    ref.invalidate(inventoryStatsQuery.provider);
                  },
                ),
              ),
          ],
        ),
      ),
      QueryPanel(
        query: orderHistoryQuery,
        argument: id,
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty)
              const EmptyNotice('No status history was returned.'),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title:
                      '${row.from == null ? 'Created' : statusLabel(row.from!)} to ${statusLabel(row.to)}',
                  label: row.createdAt.text,
                  lines: {'Note': row.note ?? 'No note'},
                ),
              ),
          ],
        ),
      ),
      const CapabilityNotice(
        'History order and money are supplied by the server. Administrative closeout, invoices, refunds, partial/backorder actions and document currency snapshots are not exposed here.',
      ),
    ],
  );
}

class OrderCreateScreen extends ConsumerWidget {
  const OrderCreateScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Legacy manual order / exact original intent',
    title: 'Create order',
    children: [
      const CapabilityNotice(
        'This creates a pending order with server-priced lines. It does not atomically reserve stock or perform customer checkout. Confirmation and reservation remain explicit operations.',
      ),
      QueryPanel(
        query: warehousesQuery,
        argument: 0,
        builder: (warehouses) => IntentForm(
          command: createOrderCommand,
          fields: [
            AdminField(
              'customer_id',
              'Customer',
              kind: FieldKind.lookup,
              required: true,
              pick: pickCustomer,
            ),
            AdminField(
              'warehouse_id',
              'Warehouse',
              kind: FieldKind.choice,
              required: true,
              choices: {
                '': 'Choose warehouse',
                for (final wh in warehouses) wh.id: '${wh.code} / ${wh.name}',
              },
            ),
            const AdminField(
              'payment_mode',
              'Payment terms',
              kind: FieldKind.choice,
              choices: {
                '': 'Use server customer default',
                'cash': 'Cash',
                'credit': 'Credit',
              },
            ),
            const AdminField(
              'scheduled_delivery_date',
              'Scheduled delivery date',
              kind: FieldKind.date,
              maxLength: 10,
            ),
            const AdminField(
              'delivery_address',
              'Delivery address',
              kind: FieldKind.multiline,
              maxLength: 500,
            ),
            const AdminField(
              'notes',
              'Order notes',
              kind: FieldKind.multiline,
              maxLength: 500,
            ),
          ],
          seed: const {'items': <Object?>[]},
          extra: (context, ref, form) => OrderLinesEditor(form),
          input: (v) => OrderInput(
            customerId: v.text('customer_id'),
            warehouseId: v.text('warehouse_id'),
            paymentMode: v.text('payment_mode'),
            scheduled: v.text('scheduled_delivery_date'),
            address: v.text('delivery_address'),
            notes: v.text('notes'),
            lines: [
              for (final row in v.value('items') as List)
                OrderLineInput(
                  JsonObject(row).uuid('product_id'),
                  JsonObject(row).string('quantity'),
                ),
            ],
          ),
          onSaved: (order) {
            ref.invalidate(ordersQuery.provider);
            ref.invalidate(orderStatsQuery.provider);
            context.go('/orders/${order.id}');
          },
        ),
      ),
    ],
  );
}

class OrderLinesEditor extends ConsumerWidget {
  const OrderLinesEditor(this.form, {super.key});
  final FormContext form;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rows = (form.values.value('items') as List?) ?? const [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (rows.isEmpty)
          const EmptyNotice(
            'Add at least one product. Prices and totals are calculated only by the server.',
          ),
        for (var index = 0; index < rows.length; index++)
          Padding(
            padding: const EdgeInsets.only(bottom: 18),
            child: Builder(
              builder: (context) {
                final row = JsonObject(rows[index]);
                final productId = row.uuid('product_id');
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    QueryPanel(
                      query: productQuery,
                      argument: productId,
                      builder: (product) => Text(
                        '${product.sku} / ${product.name}',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextFormField(
                      key: ValueKey('quantity:$productId'),
                      initialValue: row.string('quantity'),
                      enabled: !form.locked,
                      decoration: const InputDecoration(
                        labelText: 'Requested quantity',
                      ),
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      validator: (value) {
                        try {
                          decimalInput(value ?? '', places: 3, positive: true);
                          return null;
                        } on AppFailure {
                          return 'Use a positive quantity with at most 3 decimal places.';
                        }
                      },
                      onChanged: (value) {
                        final next = [
                          for (final item in rows)
                            Map<String, Object?>.from(item as Map),
                        ];
                        next[index]['quantity'] = value;
                        form.set('items', next);
                      },
                    ),
                    TextButton.icon(
                      onPressed: form.locked
                          ? null
                          : () {
                              final next = [...rows]..removeAt(index);
                              form.set('items', next);
                            },
                      icon: const Icon(Icons.remove_circle_outline),
                      label: const Text('Remove product'),
                    ),
                  ],
                );
              },
            ),
          ),
        OutlinedButton.icon(
          onPressed: form.locked || rows.length >= 200
              ? null
              : () async {
                  final product = await pickProduct(context, ref);
                  if (product == null || !context.mounted) return;
                  if (rows.any(
                    (row) => JsonObject(row).uuid('product_id') == product.id,
                  )) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text(
                          'This product is already present. Edit its quantity.',
                        ),
                      ),
                    );
                    return;
                  }
                  form.set('items', [
                    ...rows,
                    {'product_id': product.id, 'quantity': '1.000'},
                  ]);
                },
          icon: const Icon(Icons.add),
          label: const Text('Add product'),
        ),
        const SizedBox(height: 16),
      ],
    );
  }
}

Future<FieldChoice?> pickOrder(BuildContext context, String customerId) {
  final scope = ProviderScope.containerOf(
    context,
    listen: false,
  ).read(authProvider).key;
  if (scope == null) return Future.value(null);
  return showModalBottomSheet<FieldChoice>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) =>
        AccountBoundary(scope: scope, child: OrderPicker(customerId)),
  );
}

class OrderPicker extends ConsumerStatefulWidget {
  const OrderPicker(this.customerId, {super.key});
  final String customerId;
  @override
  ConsumerState<OrderPicker> createState() => _OrderPickerState();
}

class _OrderPickerState extends ConsumerState<OrderPicker> {
  int page = 1;
  @override
  Widget build(BuildContext context) => SizedBox(
    height: MediaQuery.sizeOf(context).height * .85,
    child: TaskPage(
      eyebrow: 'Server customer orders',
      title: 'Choose order',
      children: [
        QueryPanel(
          query: ordersQuery,
          argument: (page: page, status: '', customerId: widget.customerId),
          builder: (result) => Column(
            children: [
              if (result.items.isEmpty)
                const EmptyNotice('No orders on this page.'),
              for (final order in result.items.where(
                (order) =>
                    order.status != 'cancelled' &&
                    order.paymentStatus != 'paid',
              ))
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: RecordCard(
                    title: order.number,
                    status: order.status,
                    lines: {'Server due': order.due.text},
                    onTap: () => Navigator.pop(
                      context,
                      FieldChoice(order.id, order.number, order.due.text),
                    ),
                  ),
                ),
              AdminPageControls(
                page: result.page,
                total: result.total,
                hasNext: result.hasNext,
                onPage: (value) => setState(() => page = value),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}
