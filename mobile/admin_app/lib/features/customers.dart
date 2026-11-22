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

class CustomerRecord {
  CustomerRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    code = json.string('code');
    name = json.string('name');
    active = json.boolean('is_active');
    business = json.optionalString('business_name');
    phone = json.optionalString('phone');
    email = json.optionalString('email');
    gstin = json.optionalString('gstin');
    address = json.optionalString('address');
    city = json.optionalString('city');
    state = json.optionalString('state');
    pincode = json.optionalString('pincode');
    tier = json.optionalString('price_tier');
    type = json.string('customer_type');
    if (!const {'cash', 'credit'}.contains(type)) throw invalidResponse;
    limit = json.decimal('credit_limit');
    outstanding = json.decimal('outstanding');
    hold = json.decimal('credit_held');
    exposure = json.decimal('credit_exposure');
    advance = json.decimal('advance_balance');
    headroom = json.decimal('available_credit');
    cashPending = json.decimal('cash_funded_pending');
  }
  late final String id, code, name;
  late final String type;
  late final String? business,
      phone,
      email,
      gstin,
      address,
      city,
      state,
      pincode,
      tier;
  late final bool active;
  late final ServerDecimal limit,
      outstanding,
      hold,
      exposure,
      advance,
      headroom,
      cashPending;
  FieldChoice get choice => FieldChoice(id, '$code / $name', city);
  Map<String, String> get balances => {
    'Signed balance': outstanding.text,
    'Unallocated advance balance': advance.text,
    'Credit limit': limit.text,
    'Gross credit hold': hold.text,
    'Pending cash funding': cashPending.text,
    'Credit exposure': exposure.text,
    'Available headroom': headroom.text,
  };
}

class LedgerRecord {
  LedgerRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    debit = json.decimal('debit');
    credit = json.decimal('credit');
    balance = json.decimal('balance_after');
    type = json.optionalString('reference_type');
    referenceId = json.optionalUuid('reference_id');
    note = json.optionalString('note');
    createdAt = json.timestamp('created_at');
  }
  late final String id;
  late final String? type, referenceId, note;
  late final ServerDecimal debit, credit, balance;
  late final ServerTimestamp createdAt;
}

final customersQuery = SessionQuery<Paginated<CustomerRecord>, SearchPage>(
  sessionProvider: authProvider,
  load: (session, scope, arg, token) => AdminRepository(session).read(
    '/customers',
    scope,
    token,
    (raw) {
      final page = Paginated.fromJson(raw, CustomerRecord.new);
      page.requirePage(arg.page, 50);
      return page;
    },
    parameters: {
      'page': arg.page,
      'page_size': 50,
      if (arg.q.isNotEmpty) 'q': arg.q,
    },
  ),
);
final customerQuery = SessionQuery<CustomerRecord, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) =>
      AdminRepository(session)
          .read('/customers/${idPath(id)}', scope, token, (raw) {
            final value = CustomerRecord(raw);
            bindId(value.id, id);
            return value;
          }),
);
final ledgerQuery = SessionQuery<List<LedgerRecord>, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) {
    requireRoles(scope, financeWriters);
    return AdminRepository(session).read(
      '/customers/${idPath(id)}/ledger',
      scope,
      token,
      (raw) => jsonList(raw, LedgerRecord.new),
    );
  },
);
Future<FieldChoice?> pickCustomer(BuildContext context, WidgetRef ref) =>
    pickRecord(
      context,
      title: 'customer',
      query: customersQuery,
      choice: (CustomerRecord customer) => customer.choice,
    );

class CustomerInput implements AdminInput {
  const CustomerInput({
    required this.name,
    required this.limit,
    this.type = 'cash',
    this.code,
    this.business = '',
    this.phone = '',
    this.email = '',
    this.gstin = '',
    this.address = '',
    this.city = '',
    this.state = '',
    this.pincode = '',
    this.active = true,
  });
  final String name,
      limit,
      type,
      business,
      phone,
      email,
      gstin,
      address,
      city,
      state,
      pincode;
  final String? code;
  final bool active;
  @override
  Map<String, Object?> toJson() {
    if (!const {'cash', 'credit'}.contains(type)) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
    return {
      if (code != null) 'code': textInput(code!, 30, required: true),
      'name': textInput(name, 200, required: true),
      'business_name': optionalText(business, 200),
      'phone': optionalText(phone, 30),
      'email': optionalText(email, 200)?.toLowerCase(),
      'gstin': optionalText(gstin, 20),
      'address': optionalText(address),
      'city': optionalText(city, 120),
      'state': optionalText(state, 120),
      'pincode': optionalText(pincode, 15),
      'credit_limit': decimalInput(limit),
      'customer_type': type,
      if (code == null) 'is_active': active,
    };
  }
}

AdminCommand<CustomerInput, CustomerRecord> customerCommand([String? id]) =>
    AdminCommand(
      slot: id == null ? 'customer:create' : 'customer:$id:edit',
      title: id == null
          ? 'Create customer record'
          : 'Save contact and credit settings',
      group: id == null ? 'customer:create' : 'customer:$id',
      route: id == null ? '/customers/new' : '/customers/$id/edit',
      roles: financeWriters,
      endpoint: JsonMutationEndpoint(
        method: id == null ? MutationMethod.post : MutationMethod.patch,
        path: id == null ? '/customers' : '/customers/${idPath(id)}',
        expectedStatus: id == null ? 201 : 200,
        encode: (input) => input.toJson(),
        decode: (raw, original) {
          final value = CustomerRecord(raw);
          final body = original.body!;
          if (id != null) bindId(value.id, id);
          if (value.name != body['name'] ||
              value.business != body['business_name'] ||
              value.phone != body['phone'] ||
              value.email != body['email'] ||
              value.gstin != body['gstin'] ||
              value.address != body['address'] ||
              value.city != body['city'] ||
              value.state != body['state'] ||
              value.pincode != body['pincode'] ||
              value.type != body['customer_type'] ||
              (body.containsKey('code') && value.code != body['code']) ||
              (body.containsKey('is_active') &&
                  value.active != body['is_active'])) {
            throw invalidResponse;
          }
          requireDecimalBinding(value.limit, body['credit_limit']);
          return value;
        },
      ),
    );

class CustomersScreen extends ConsumerStatefulWidget {
  const CustomersScreen({super.key});
  @override
  ConsumerState<CustomersScreen> createState() => _CustomersScreenState();
}

class _CustomersScreenState extends ConsumerState<CustomersScreen> {
  int page = 1;
  String q = '';
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Accounts / server balances',
    title: 'Customers',
    actions: [
      recordLink(context, '/customers/new', 'New customer record'),
      OutlinedButton(
        onPressed: ref.read(customersQuery.refreshProvider((page: page, q: q))),
        child: const Text('Refresh'),
      ),
    ],
    children: [
      SearchBox(
        label: 'Search customer or code',
        onSearch: (value) => setState(() {
          q = value;
          page = 1;
        }),
      ),
      QueryPanel(
        query: customersQuery,
        argument: (page: page, q: q),
        builder: (result) => Column(
          children: [
            if (result.items.isEmpty)
              const EmptyNotice('No customers match this search.'),
            for (final row in result.items)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: row.name,
                  label: row.code,
                  status: row.active ? 'active' : 'inactive',
                  lines: {
                    'Signed balance': row.outstanding.text,
                    'Unallocated advance': row.advance.text,
                    'Credit exposure': row.exposure.text,
                    'City': row.city ?? 'Not set',
                  },
                  onTap: () => context.go('/customers/${row.id}'),
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

class CustomerDetailScreen extends ConsumerWidget {
  const CustomerDetailScreen(this.id, {super.key});
  final String id;
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Customer / authoritative account values',
    title: 'Customer account',
    actions: [
      recordLink(context, '/customers/$id/edit', 'Edit contact / credit'),
      recordLink(context, '/pricing?customer_id=$id', 'Customer pricing'),
      OutlinedButton(
        onPressed: () {
          ref.read(customerQuery.refreshProvider(id))();
          ref.read(ledgerQuery.refreshProvider(id))();
        },
        child: const Text('Refresh'),
      ),
    ],
    children: [
      QueryPanel(
        query: customerQuery,
        argument: id,
        builder: (customer) => Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            RecordCard(
              title: customer.name,
              label: customer.code,
              status: customer.active ? 'active' : 'inactive',
              lines: {
                'Business name': customer.business ?? 'Not set',
                'Phone': customer.phone ?? 'Not set',
                'Email (contact only)': customer.email ?? 'Not set',
                'Address': customer.address ?? 'Not set',
                'Account type': customer.type,
                'Pricing tier': customer.tier ?? 'Base pricing',
              },
            ),
            const SizedBox(height: 16),
            RecordCard(
              title: 'Server account balances',
              lines: customer.balances,
            ),
          ],
        ),
      ),
      const CapabilityNotice(
        'The ledger below is the current customer ledger, not a full general ledger or immutable statement. Customer login provisioning/linking, invoices, refunds and document currency snapshots are separate work.',
      ),
      QueryPanel(
        query: ledgerQuery,
        argument: id,
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty)
              const EmptyNotice('No ledger entries for this customer.'),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: row.type?.replaceAll('_', ' ') ?? 'Ledger entry',
                  label: row.createdAt.text,
                  lines: {
                    'Debit': row.debit.text,
                    'Credit': row.credit.text,
                    'Server balance after': row.balance.text,
                    'Note': row.note ?? 'No note',
                  },
                ),
              ),
          ],
        ),
      ),
    ],
  );
}

class CustomerEditScreen extends ConsumerWidget {
  const CustomerEditScreen({this.id, super.key});
  final String? id;
  Widget _form(BuildContext context, WidgetRef ref, CustomerRecord? customer) =>
      IntentForm(
        command: customerCommand(id),
        fields: [
          if (customer == null)
            const AdminField(
              'code',
              'Customer code',
              required: true,
              maxLength: 30,
            ),
          AdminField(
            'name',
            'Customer name',
            initial: customer?.name ?? '',
            required: true,
          ),
          AdminField(
            'business_name',
            'Business name',
            initial: customer?.business ?? '',
          ),
          AdminField(
            'phone',
            'Phone',
            initial: customer?.phone ?? '',
            maxLength: 30,
          ),
          AdminField(
            'email',
            'Contact email',
            initial: customer?.email ?? '',
            maxLength: 200,
          ),
          AdminField(
            'gstin',
            'GSTIN',
            initial: customer?.gstin ?? '',
            maxLength: 20,
          ),
          AdminField(
            'address',
            'Address',
            initial: customer?.address ?? '',
            kind: FieldKind.multiline,
            maxLength: 500,
          ),
          AdminField(
            'city',
            'City',
            initial: customer?.city ?? '',
            maxLength: 120,
          ),
          AdminField(
            'state',
            'State',
            initial: customer?.state ?? '',
            maxLength: 120,
          ),
          AdminField(
            'pincode',
            'Postal code',
            initial: customer?.pincode ?? '',
            maxLength: 15,
          ),
          AdminField(
            'credit_limit',
            'Credit limit',
            initial: customer?.limit.text ?? '0.00',
            required: true,
            kind: FieldKind.decimal,
            help: 'The server protects existing debt, exposure and holds.',
          ),
          AdminField(
            'customer_type',
            'Account type',
            initial: customer?.type ?? 'cash',
            required: true,
            kind: FieldKind.choice,
            choices: const {'cash': 'Cash', 'credit': 'Credit'},
          ),
          if (customer != null)
            AdminField(
              'is_active',
              'Active customer record',
              initial: customer.active,
              kind: FieldKind.boolean,
            ),
        ],
        input: (v) => CustomerInput(
          code: customer == null ? v.text('code') : null,
          name: v.text('name'),
          limit: v.text('credit_limit'),
          type: v.text('customer_type'),
          business: v.text('business_name'),
          phone: v.text('phone'),
          email: v.text('email'),
          gstin: v.text('gstin'),
          address: v.text('address'),
          city: v.text('city'),
          state: v.text('state'),
          pincode: v.text('pincode'),
          active: v.boolean('is_active'),
        ),
        onSaved: (value) {
          ref.invalidate(customersQuery.provider);
          ref.invalidate(customerQuery.provider);
          context.go('/customers/${value.id}');
        },
      );
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Contact and credit / no account credentials',
    title: id == null ? 'New customer record' : 'Edit customer',
    children: [
      const CapabilityNotice(
        'This edits a business customer record. It does not create a login, change an account password, verify an email or bypass server credit rules.',
      ),
      if (id == null)
        _form(context, ref, null)
      else
        QueryPanel(
          query: customerQuery,
          argument: id!,
          builder: (customer) => _form(context, ref, customer),
        ),
    ],
  );
}
