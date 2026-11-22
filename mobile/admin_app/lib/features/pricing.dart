import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../core/contracts.dart';
import '../core/forms.dart';
import '../core/intents.dart';
import '../core/navigation.dart';
import '../core/providers.dart';
import '../core/widgets.dart';
import 'catalog.dart';
import 'customers.dart';

class TierRecord {
  TierRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    name = json.string('name');
    discount = json.decimal('discount_pct');
  }
  late final String id, name;
  late final ServerDecimal discount;
}

class OverrideRecord {
  OverrideRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    customerId = json.uuid('customer_id');
    productId = json.uuid('product_id');
    price = json.decimal('price');
  }
  late final String id, customerId, productId;
  late final ServerDecimal price;
}

class ResolvedPrice {
  ResolvedPrice(Object? raw) {
    final json = JsonObject(raw);
    customerId = json.uuid('customer_id');
    productId = json.uuid('product_id');
    price = json.decimal('price');
  }
  late final String customerId, productId;
  late final ServerDecimal price;
}

final tiersQuery = SessionQuery<List<TierRecord>, int>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) => AdminRepository(session).read(
    '/pricing/tiers',
    scope,
    token,
    (raw) => jsonList(raw, TierRecord.new),
  ),
);
final overridesQuery = SessionQuery<List<OverrideRecord>, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) =>
      AdminRepository(session)
          .read('/customers/${idPath(id)}/prices', scope, token, (raw) {
            final rows = jsonList(raw, OverrideRecord.new);
            for (final row in rows) {
              bindId(row.customerId, id);
            }
            return rows;
          }),
);
final resolvedPriceQuery =
    SessionQuery<ResolvedPrice, ({String customerId, String productId})>(
      sessionProvider: authProvider,
      load: (session, scope, arg, token) => AdminRepository(session).read(
        '/pricing/resolve',
        scope,
        token,
        (raw) {
          final value = ResolvedPrice(raw);
          bindId(value.customerId, arg.customerId);
          bindId(value.productId, arg.productId);
          return value;
        },
        parameters: {
          'customer_id': idPath(arg.customerId),
          'product_id': idPath(arg.productId),
        },
      ),
    );

class TierInput implements AdminInput {
  const TierInput(this.discount, {this.name});
  final String discount;
  final String? name;
  @override
  Map<String, Object?> toJson() => {
    'discount_pct': decimalInput(discount),
    if (name != null) 'name': textInput(name!, 60, required: true),
  };
}

AdminCommand<TierInput, TierRecord> tierCommand([String? id]) => AdminCommand(
  slot: id == null ? 'tier:create' : 'tier:$id:edit',
  group: id == null ? 'tier:create' : 'tier:$id',
  title: id == null ? 'Create pricing tier' : 'Save tier discount',
  route: '/pricing',
  roles: operators,
  endpoint: JsonMutationEndpoint(
    method: id == null ? MutationMethod.post : MutationMethod.patch,
    path: id == null ? '/pricing/tiers' : '/pricing/tiers/${idPath(id)}',
    expectedStatus: id == null ? 201 : 200,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = TierRecord(raw);
      if (id != null) bindId(value.id, id);
      if (original.body!.containsKey('name') &&
          value.name != original.body!['name']) {
        throw invalidResponse;
      }
      requireDecimalBinding(value.discount, original.body!['discount_pct']);
      return value;
    },
  ),
);

class TierAssignmentInput implements AdminInput {
  const TierAssignmentInput(this.id);
  final String? id;
  @override
  Map<String, Object?> toJson() => {
    'tier_id': id == null || id == '' ? null : idPath(id!),
  };
}

AdminCommand<TierAssignmentInput, CustomerRecord> assignmentCommand(
  String customerId,
  SessionController session,
) => AdminCommand(
  slot: 'customer:$customerId:tier',
  group: 'customer:$customerId',
  title: 'Assign customer tier',
  route: '/pricing?customer_id=$customerId',
  roles: financeWriters,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.patch,
    path: '/customers/${idPath(customerId)}/pricing-tier',
    expectedStatus: 200,
    encode: (input) => input.toJson(),
    decode: (raw, original) async {
      final customer = CustomerRecord(raw);
      bindId(customer.id, customerId);
      final tierId = original.body!['tier_id'];
      if (tierId == null) {
        if (customer.tier != null) throw invalidResponse;
        return customer;
      }
      final tiers = jsonList(
        await session.get('/pricing/tiers', scope: original.scope),
        TierRecord.new,
      );
      final tier = tiers.where((tier) => tier.id == tierId).firstOrNull;
      if (tier == null || customer.tier != tier.name) throw invalidResponse;
      return customer;
    },
  ),
);

class OverrideInput implements AdminInput {
  const OverrideInput(this.productId, this.price);
  final String productId, price;
  @override
  Map<String, Object?> toJson() => {
    'product_id': idPath(productId),
    'price': decimalInput(price),
  };
}

AdminCommand<OverrideInput, OverrideRecord> overrideCommand(
  String customerId,
) => AdminCommand(
  slot: 'customer:$customerId:override',
  group: 'customer:$customerId',
  title: 'Save customer price override',
  route: '/pricing?customer_id=$customerId',
  roles: financeWriters,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/customers/${idPath(customerId)}/prices',
    expectedStatus: 200,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = OverrideRecord(raw);
      bindId(value.customerId, customerId);
      bindId(value.productId, original.body!['product_id'] as String);
      requireDecimalBinding(value.price, original.body!['price']);
      return value;
    },
  ),
);
AdminCommand<NoInput, Accepted> removeOverrideCommand(
  String customerId,
  String productId,
) => AdminCommand(
  slot: 'customer:$customerId:remove:$productId',
  group: 'customer:$customerId',
  title: 'Remove this override',
  route: '/pricing?customer_id=$customerId',
  roles: financeWriters,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.delete,
    path: '/customers/${idPath(customerId)}/prices/${idPath(productId)}',
    expectedStatus: 204,
    encode: (_) => null,
    decode: (_, _) => const Accepted(),
  ),
);

class PricingScreen extends ConsumerStatefulWidget {
  const PricingScreen({this.customerId, super.key});
  final String? customerId;
  @override
  ConsumerState<PricingScreen> createState() => _PricingScreenState();
}

class _PricingScreenState extends ConsumerState<PricingScreen> {
  String? customerId, productId;
  String? customerLabel, productLabel;
  @override
  void initState() {
    super.initState();
    customerId = widget.customerId;
  }

  @override
  Widget build(BuildContext context) {
    final role = ref.watch(authProvider).key?.role;
    return TaskPage(
      eyebrow: 'Server pricing / no client calculations',
      title: 'Pricing',
      actions: [
        OutlinedButton(
          onPressed: ref.read(tiersQuery.refreshProvider(0)),
          child: const Text('Refresh tiers'),
        ),
      ],
      children: [
        const CapabilityNotice(
          'Overrides, tier discounts and base prices are resolved by the server for future orders. This does not reprice historical orders. Promotion/time-window APIs are not connected.',
        ),
        QueryPanel(
          query: tiersQuery,
          argument: 0,
          builder: (tiers) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (tiers.isEmpty)
                const EmptyNotice('No pricing tiers have been created.'),
              for (final tier in tiers)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: RecordCard(
                    title: tier.name,
                    lines: {'Discount (%)': tier.discount.text},
                    actions: [
                      if (operators.contains(role))
                        OutlinedButton(
                          onPressed: () => showAccountSheet(
                            context,
                            builder: (_) => SizedBox(
                              height: MediaQuery.sizeOf(context).height * .8,
                              child: TaskPage(
                                eyebrow: 'Immutable tier name',
                                title: tier.name,
                                children: [
                                  IntentForm(
                                    command: tierCommand(tier.id),
                                    fields: [
                                      AdminField(
                                        'discount_pct',
                                        'Discount (%)',
                                        kind: FieldKind.decimal,
                                        initial: tier.discount.text,
                                        required: true,
                                      ),
                                    ],
                                    input: (v) =>
                                        TierInput(v.text('discount_pct')),
                                    onSaved: (_) {
                                      ref.read(tiersQuery.refreshProvider(0))();
                                      Navigator.pop(context);
                                    },
                                  ),
                                ],
                              ),
                            ),
                          ),
                          child: const Text('Edit discount'),
                        ),
                    ],
                  ),
                ),
              if (operators.contains(role))
                IntentForm(
                  command: tierCommand(),
                  fields: const [
                    AdminField(
                      'name',
                      'New tier name',
                      required: true,
                      maxLength: 30,
                      help: 'New assignable names fit the customer 30-character tier reference.',
                    ),
                    AdminField(
                      'discount_pct',
                      'Discount (%)',
                      required: true,
                      kind: FieldKind.decimal,
                    ),
                  ],
                  input: (v) =>
                      TierInput(v.text('discount_pct'), name: v.text('name')),
                  onSaved: (_) => ref.read(tiersQuery.refreshProvider(0))(),
                ),
            ],
          ),
        ),
        OutlinedButton.icon(
          onPressed: () async {
            final picked = await pickCustomer(context, ref);
            if (picked != null && mounted) {
              setState(() {
                customerId = picked.id;
                customerLabel = picked.label;
                productId = null;
              });
            }
          },
          icon: const Icon(Icons.person_search),
          label: Text(customerLabel ?? 'Choose customer for server pricing'),
        ),
        if (customerId != null)
          QueryPanel(
            query: customerQuery,
            argument: customerId!,
            builder: (customer) => RecordCard(
              title: customer.name,
              label: customer.code,
              lines: {'Assigned tier': customer.tier ?? 'Base pricing'},
            ),
          ),
        if (customerId != null)
          OutlinedButton.icon(
            onPressed: () async {
              final picked = await pickProduct(context, ref);
              if (picked != null && mounted) {
                setState(() {
                  productId = picked.id;
                  productLabel = picked.label;
                });
              }
            },
            icon: const Icon(Icons.search),
            label: Text(productLabel ?? 'Choose product to resolve'),
          ),
        if (customerId != null && productId != null)
          QueryPanel(
            query: resolvedPriceQuery,
            argument: (customerId: customerId!, productId: productId!),
            builder: (price) => RecordCard(
              title: 'Effective server price',
              lines: {'Price': price.price.text},
            ),
          ),
        if (customerId != null && financeWriters.contains(role))
          CustomerPricingPanel(customerId!),
      ],
    );
  }
}

class CustomerPricingPanel extends ConsumerWidget {
  const CustomerPricingPanel(this.customerId, {super.key});
  final String customerId;
  @override
  Widget build(BuildContext context, WidgetRef ref) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      QueryPanel(
        query: tiersQuery,
        argument: 0,
        builder: (tiers) => IntentForm(
          key: ValueKey('tier-assignment:$customerId'),
          command: assignmentCommand(
            customerId,
            ref.read(authProvider.notifier),
          ),
          fields: [
            AdminField(
              'tier_id',
              'Customer tier',
              kind: FieldKind.choice,
              choices: {
                '': 'Clear tier / base pricing',
                for (final tier in tiers) tier.id: tier.name,
              },
            ),
          ],
          input: (v) => TierAssignmentInput(v.text('tier_id')),
          onSaved: (_) {
            ref.invalidate(customerQuery.provider);
            ref.invalidate(resolvedPriceQuery.provider);
          },
        ),
      ),
      const SizedBox(height: 24),
      IntentForm(
        key: ValueKey('override:$customerId'),
        command: overrideCommand(customerId),
        fields: [
          AdminField(
            'product_id',
            'Override product',
            kind: FieldKind.lookup,
            required: true,
            pick: pickProduct,
          ),
          const AdminField(
            'price',
            'Customer price',
            kind: FieldKind.decimal,
            required: true,
            help: 'Zero is a valid explicit override; the server validates price policy.',
          ),
        ],
        input: (v) => OverrideInput(v.text('product_id'), v.text('price')),
        onSaved: (_) {
          ref.invalidate(overridesQuery.provider);
          ref.invalidate(resolvedPriceQuery.provider);
        },
      ),
      const SizedBox(height: 24),
      QueryPanel(
        query: overridesQuery,
        argument: customerId,
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty)
              const EmptyNotice('No explicit product price overrides.'),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: QueryPanel(
                  query: productQuery,
                  argument: row.productId,
                  builder: (product) => RecordCard(
                    title: product.name,
                    label: product.sku,
                    lines: {'Override price': row.price.text},
                    actions: [
                      SizedBox(
                        width: double.infinity,
                        child: IntentForm(
                          command: removeOverrideCommand(
                            customerId,
                            row.productId,
                          ),
                          fields: const [],
                          input: (_) => const NoInput(),
                          onSaved: (_) {
                            ref.invalidate(overridesQuery.provider);
                            ref.invalidate(resolvedPriceQuery.provider);
                          },
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    ],
  );
}
