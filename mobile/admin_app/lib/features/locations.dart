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

class WarehouseRecord {
  WarehouseRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    code = json.string('code');
    name = json.string('name');
    active = json.boolean('is_active');
    address = json.optionalString('address');
    city = json.optionalString('city');
    state = json.optionalString('state');
    pincode = json.optionalString('pincode');
  }
  late final String id, code, name;
  late final String? address, city, state, pincode;
  late final bool active;
}

class RackRecord {
  RackRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    warehouseId = json.uuid('warehouse_id');
    code = json.string('code');
    label = json.string('label');
  }
  late final String id, warehouseId, code, label;
}

class ShelfRecord {
  ShelfRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    warehouseId = json.uuid('warehouse_id');
    rackId = json.uuid('rack_id');
    code = json.string('code');
    label = json.string('label');
  }
  late final String id, warehouseId, rackId, code, label;
}

class InventoryStats {
  InventoryStats(Object? raw) {
    final json = JsonObject(raw);
    products = json.integer('total_products');
    low = json.integer('low_stock');
    out = json.integer('out_of_stock');
    value = json.decimal('total_inventory_value');
    reserved = json.decimal('total_reserved');
  }
  late final int products, low, out;
  late final ServerDecimal value, reserved;
  Map<String, String> get lines => {
    'Active products': '$products',
    'Low-stock products': '$low',
    'Out-of-stock products': '$out',
    'Inventory value (server)': value.text,
    'Reserved quantity (server)': reserved.text,
  };
}

class InventoryRecord {
  InventoryRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    productId = json.uuid('product_id');
    warehouseId = json.uuid('warehouse_id');
    sku = json.string('product_sku');
    productName = json.string('product_name');
    warehouseName = json.string('warehouse_name');
    rackId = json.optionalUuid('rack_id');
    shelfId = json.optionalUuid('shelf_id');
    batchId = json.optionalUuid('batch_id');
    quantity = json.decimal('quantity');
    reserved = json.decimal('reserved_qty');
    available = json.decimal('available_qty');
    transit = json.decimal('in_transit_qty');
    damaged = json.decimal('damaged_qty');
    low = json.boolean('low_stock');
  }
  late final String id, productId, warehouseId, sku, productName, warehouseName;
  late final String? rackId, shelfId, batchId;
  late final ServerDecimal quantity, reserved, available, transit, damaged;
  late final bool low;
}

class MovementRecord {
  MovementRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    productId = json.uuid('product_id');
    warehouseId = json.uuid('warehouse_id');
    type = json.string('movement_type');
    quantity = json.decimal('quantity');
    createdAt = json.timestamp('created_at');
    note = json.optionalString('note');
    referenceType = json.optionalString('reference_type');
    referenceId = json.optionalUuid('reference_id');
  }
  late final String id, productId, warehouseId, type;
  late final String? note, referenceType, referenceId;
  late final ServerDecimal quantity;
  late final ServerTimestamp createdAt;
}

final warehousesQuery = SessionQuery<List<WarehouseRecord>, int>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) => AdminRepository(session).read(
    '/warehouses',
    scope,
    token,
    (raw) => jsonList(raw, WarehouseRecord.new),
  ),
);
final racksQuery = SessionQuery<List<RackRecord>, String>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) =>
      AdminRepository(session)
          .read('/warehouses/${idPath(id)}/racks', scope, token, (raw) {
            final rows = jsonList(raw, RackRecord.new);
            for (final row in rows) {
              bindId(row.warehouseId, id);
            }
            return rows;
          }),
);
final shelvesQuery =
    SessionQuery<List<ShelfRecord>, ({String warehouseId, String rackId})>(
      sessionProvider: authProvider,
      load: (session, scope, arg, token) => AdminRepository(session).read(
        '/warehouses/racks/${idPath(arg.rackId)}/shelves',
        scope,
        token,
        (raw) {
          final rows = jsonList(raw, ShelfRecord.new);
          for (final row in rows) {
            bindId(row.rackId, arg.rackId);
            bindId(row.warehouseId, arg.warehouseId);
          }
          return rows;
        },
      ),
    );
final inventoryStatsQuery = SessionQuery<InventoryStats, int>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) =>
      AdminRepository(session)
          .read('/inventory/stats', scope, token, InventoryStats.new),
);
typedef InventoryFilter = ({String q, String? warehouseId, bool lowOnly});
final inventoryQuery = SessionQuery<List<InventoryRecord>, InventoryFilter>(
  sessionProvider: authProvider,
  load: (session, scope, arg, token) => AdminRepository(session).read(
    '/inventory',
    scope,
    token,
    (raw) {
      final rows = jsonList(raw, InventoryRecord.new);
      for (final row in rows) {
        if (arg.warehouseId != null) bindId(row.warehouseId, arg.warehouseId!);
        if (arg.lowOnly && !row.low) throw invalidResponse;
      }
      return rows;
    },
    parameters: {
      if (arg.q.isNotEmpty) 'q': arg.q,
      if (arg.warehouseId != null) 'warehouse_id': idPath(arg.warehouseId!),
      'low_stock_only': arg.lowOnly,
    },
  ),
);
final movementsQuery = SessionQuery<List<MovementRecord>, String?>(
  sessionProvider: authProvider,
  load: (session, scope, id, token) => AdminRepository(session)
      .read('/inventory/movements', scope, token, (raw) {
        final rows = jsonList(raw, MovementRecord.new);
        for (final row in rows) {
          if (id != null) bindId(row.productId, id);
        }
        return rows;
      }, parameters: {'limit': 100, if (id != null) 'product_id': idPath(id)}),
);

class WarehouseInput implements AdminInput {
  const WarehouseInput(
    this.code,
    this.name,
    this.address,
    this.city,
    this.state,
    this.pincode,
  );
  final String code, name, address, city, state, pincode;
  @override
  Map<String, Object?> toJson() => {
    'code': textInput(code, 30, required: true),
    'name': textInput(name, 200, required: true),
    'address': optionalText(address),
    'city': optionalText(city, 100),
    'state': optionalText(state, 100),
    'pincode': optionalText(pincode, 20),
  };
}

final warehouseCommand = AdminCommand<WarehouseInput, WarehouseRecord>(
  slot: 'warehouse:create',
  title: 'Create warehouse',
  route: '/warehouses/new',
  roles: operators,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/warehouses',
    expectedStatus: 201,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = WarehouseRecord(raw);
      final body = original.body!;
      if (value.code != body['code'] ||
          value.name != body['name'] ||
          value.address != body['address'] ||
          value.city != body['city'] ||
          value.state != body['state'] ||
          value.pincode != body['pincode']) {
        throw invalidResponse;
      }
      return value;
    },
  ),
);

class RackInput implements AdminInput {
  const RackInput(this.warehouseId, this.code, this.label);
  final String warehouseId, code, label;
  @override
  Map<String, Object?> toJson() => {
    'warehouse_id': idPath(warehouseId),
    'code': textInput(code, 30, required: true),
    'label': textInput(label, 120, required: true),
  };
}

AdminCommand<RackInput, RackRecord> rackCommand(String warehouseId) =>
    AdminCommand(
      slot: 'warehouse:$warehouseId:rack',
      title: 'Create rack',
      route: '/warehouses/$warehouseId',
      roles: operators,
      endpoint: JsonMutationEndpoint(
        method: MutationMethod.post,
        path: '/warehouses/racks',
        expectedStatus: 201,
        encode: (input) {
          bindId(idPath(input.warehouseId), warehouseId);
          return input.toJson();
        },
        decode: (raw, original) {
          final value = RackRecord(raw);
          bindId(value.warehouseId, original.body!['warehouse_id'] as String);
          if (value.code != original.body!['code'] ||
              value.label != original.body!['label']) {
            throw invalidResponse;
          }
          return value;
        },
      ),
    );

class ShelfInput implements AdminInput {
  const ShelfInput(this.rackId, this.code, this.label);
  final String rackId, code, label;
  @override
  Map<String, Object?> toJson() => {
    'rack_id': idPath(rackId),
    'code': textInput(code, 30, required: true),
    'label': textInput(label, 120, required: true),
  };
}

AdminCommand<ShelfInput, ShelfRecord> shelfCommand(
  String warehouseId,
  String rackId,
) => AdminCommand(
  slot: 'rack:$rackId:shelf',
  title: 'Create shelf',
  route: '/warehouses/$warehouseId/racks/$rackId',
  roles: operators,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/warehouses/shelves',
    expectedStatus: 201,
    encode: (input) {
      bindId(idPath(input.rackId), rackId);
      return input.toJson();
    },
    decode: (raw, original) {
      final value = ShelfRecord(raw);
      bindId(value.rackId, original.body!['rack_id'] as String);
      bindId(value.warehouseId, warehouseId);
      if (value.code != original.body!['code'] ||
          value.label != original.body!['label']) {
        throw invalidResponse;
      }
      return value;
    },
  ),
);

class AdjustmentInput implements AdminInput {
  const AdjustmentInput({
    required this.productId,
    required this.warehouseId,
    required this.delta,
    this.rackId,
    this.shelfId,
    this.note,
  });
  final String productId, warehouseId, delta;
  final String? rackId, shelfId, note;
  @override
  Map<String, Object?> toJson() => {
    'product_id': idPath(productId),
    'warehouse_id': idPath(warehouseId),
    'rack_id': rackId == null || rackId == '' ? null : idPath(rackId!),
    'shelf_id': shelfId == null || shelfId == '' ? null : idPath(shelfId!),
    'batch_id': null,
    'delta_qty': decimalInput(delta, places: 3, signed: true),
    'note': optionalText(note ?? ''),
  };
}

final adjustmentCommand = AdminCommand<AdjustmentInput, InventoryRecord>(
  slot: 'inventory:adjust',
  title: 'Record adjustment',
  route: '/inventory/adjust',
  roles: operators,
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/inventory/adjust',
    expectedStatus: 200,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = InventoryRecord(raw);
      final body = original.body!;
      if (value.productId != body['product_id'] ||
          value.warehouseId != body['warehouse_id'] ||
          value.rackId != body['rack_id'] ||
          value.shelfId != body['shelf_id'] ||
          value.batchId != body['batch_id']) {
        throw invalidResponse;
      }
      return value;
    },
  ),
);

class WarehousesScreen extends ConsumerWidget {
  const WarehousesScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Locations / physical stock',
    title: 'Warehouses',
    actions: [
      recordLink(context, '/warehouses/new', 'Create warehouse'),
      OutlinedButton(
        onPressed: ref.read(warehousesQuery.refreshProvider(0)),
        child: const Text('Refresh'),
      ),
    ],
    children: [
      QueryPanel(
        query: warehousesQuery,
        argument: 0,
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty) const EmptyNotice('No warehouses exist yet.'),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: row.name,
                  label: row.code,
                  status: row.active ? 'active' : 'inactive',
                  lines: {
                    'City': row.city ?? 'Not set',
                    'Address': row.address ?? 'Not set',
                  },
                  onTap: () => context.go('/warehouses/${row.id}'),
                ),
              ),
          ],
        ),
      ),
      const CapabilityNotice(
        'Warehouse access associations, transfers, expiry/damage intake and nearest-warehouse policies are separate backend work. These screens browse and create actual locations.',
      ),
    ],
  );
}

class WarehouseCreateScreen extends ConsumerWidget {
  const WarehouseCreateScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Locations',
    title: 'New warehouse',
    children: [
      IntentForm(
        command: warehouseCommand,
        fields: const [
          AdminField('code', 'Warehouse code', required: true, maxLength: 30),
          AdminField('name', 'Warehouse name', required: true),
          AdminField(
            'address',
            'Address',
            kind: FieldKind.multiline,
            maxLength: 500,
          ),
          AdminField('city', 'City', maxLength: 100),
          AdminField('state', 'State', maxLength: 100),
          AdminField('pincode', 'Postal code', maxLength: 20),
        ],
        input: (v) => WarehouseInput(
          v.text('code'),
          v.text('name'),
          v.text('address'),
          v.text('city'),
          v.text('state'),
          v.text('pincode'),
        ),
        onSaved: (value) {
          ref.invalidate(warehousesQuery.provider);
          context.go('/warehouses/${value.id}');
        },
      ),
    ],
  );
}

class WarehouseDetailScreen extends ConsumerWidget {
  const WarehouseDetailScreen(this.id, {super.key});
  final String id;
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Warehouse / racks',
    title: 'Warehouse detail',
    actions: [recordLink(context, '/warehouses', 'Warehouses')],
    children: [
      QueryPanel(
        query: warehousesQuery,
        argument: 0,
        builder: (rows) {
          final warehouse = rows.where((row) => row.id == id).firstOrNull;
          if (warehouse == null) {
            return const EmptyNotice('Warehouse not found in this account.');
          }
          return RecordCard(
            title: warehouse.name,
            label: warehouse.code,
            lines: {
              'Address': warehouse.address ?? 'Not set',
              'City': warehouse.city ?? 'Not set',
            },
          );
        },
      ),
      QueryPanel(
        query: racksQuery,
        argument: id,
        builder: (racks) => Column(
          children: [
            if (racks.isEmpty) const EmptyNotice('No racks in this warehouse.'),
            for (final rack in racks)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: rack.label,
                  label: rack.code,
                  onTap: () => context.go('/warehouses/$id/racks/${rack.id}'),
                ),
              ),
          ],
        ),
      ),
      IntentForm(
        command: rackCommand(id),
        fields: const [
          AdminField('code', 'Rack code', required: true, maxLength: 30),
          AdminField('label', 'Rack label', required: true, maxLength: 120),
        ],
        input: (v) => RackInput(id, v.text('code'), v.text('label')),
        onSaved: (_) => ref.read(racksQuery.refreshProvider(id))(),
      ),
    ],
  );
}

class RackDetailScreen extends ConsumerWidget {
  const RackDetailScreen(this.warehouseId, this.rackId, {super.key});
  final String warehouseId, rackId;
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Warehouse / rack / shelves',
    title: 'Shelves',
    actions: [recordLink(context, '/warehouses/$warehouseId', 'Warehouse')],
    children: [
      QueryPanel(
        query: shelvesQuery,
        argument: (warehouseId: warehouseId, rackId: rackId),
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty) const EmptyNotice('No shelves on this rack.'),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(title: row.label, label: row.code),
              ),
          ],
        ),
      ),
      IntentForm(
        command: shelfCommand(warehouseId, rackId),
        fields: const [
          AdminField('code', 'Shelf code', required: true, maxLength: 30),
          AdminField('label', 'Shelf label', required: true, maxLength: 120),
        ],
        input: (v) => ShelfInput(rackId, v.text('code'), v.text('label')),
        onSaved: (_) => ref.read(
          shelvesQuery.refreshProvider((
            warehouseId: warehouseId,
            rackId: rackId,
          )),
        )(),
      ),
    ],
  );
}

class InventoryScreen extends ConsumerStatefulWidget {
  const InventoryScreen({super.key});
  @override
  ConsumerState<InventoryScreen> createState() => _InventoryScreenState();
}

class _InventoryScreenState extends ConsumerState<InventoryScreen> {
  String q = '';
  String? warehouseId;
  bool lowOnly = false;
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Live server stock',
    title: 'Inventory',
    actions: [
      recordLink(context, '/inventory/adjust', 'Adjust stock'),
      recordLink(context, '/inventory/movements', 'Movements'),
      OutlinedButton(
        onPressed: () {
          ref.read(inventoryStatsQuery.refreshProvider(0))();
          ref.read(
            inventoryQuery.refreshProvider((
              q: q,
              warehouseId: warehouseId,
              lowOnly: lowOnly,
            )),
          )();
        },
        child: const Text('Refresh'),
      ),
    ],
    children: [
      QueryPanel(
        query: inventoryStatsQuery,
        argument: 0,
        builder: (stats) =>
            RecordCard(title: 'Server inventory counters', lines: stats.lines),
      ),
      SearchBox(
        label: 'Search product name or SKU',
        onSearch: (value) => setState(() => q = value),
      ),
      QueryPanel(
        query: warehousesQuery,
        argument: 0,
        builder: (rows) => DropdownButtonFormField<String>(
          initialValue: warehouseId ?? '',
          isExpanded: true,
          itemHeight: null,
          decoration: const InputDecoration(labelText: 'Warehouse filter'),
          items: [
            const DropdownMenuItem(value: '', child: Text('All warehouses')),
            for (final row in rows)
              DropdownMenuItem(value: row.id, child: Text(row.name)),
          ],
          onChanged: (value) =>
              setState(() => warehouseId = value == '' ? null : value),
        ),
      ),
      SwitchListTile(
        title: const Text('Server-flagged low stock only'),
        value: lowOnly,
        onChanged: (value) => setState(() => lowOnly = value),
      ),
      QueryPanel(
        query: inventoryQuery,
        argument: (q: q, warehouseId: warehouseId, lowOnly: lowOnly),
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty)
              const EmptyNotice('No stock rows match these filters.'),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: row.productName,
                  label: '${row.sku} / ${row.warehouseName}',
                  status: row.low ? 'low stock' : 'available',
                  lines: {
                    'On hand': row.quantity.text,
                    'Reserved': row.reserved.text,
                    'Available': row.available.text,
                    'In transit': row.transit.text,
                    'Damaged': row.damaged.text,
                  },
                  actions: [
                    recordLink(
                      context,
                      '/inventory/movements?product_id=${row.productId}',
                      'Product movements',
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

class AdjustmentScreen extends ConsumerWidget {
  const AdjustmentScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Audited correction / server validation',
    title: 'Stock adjustment',
    children: [
      const CapabilityNotice(
        'Use a signed quantity delta. Stock, reservations and location eligibility are validated by the server. This is not transfer, return or damage intake, and no offline replay is promised.',
      ),
      QueryPanel(
        query: warehousesQuery,
        argument: 0,
        builder: (warehouses) => IntentForm(
          command: adjustmentCommand,
          fields: [
            AdminField(
              'product_id',
              'Product',
              kind: FieldKind.lookup,
              required: true,
              pick: pickProduct,
            ),
            AdminField(
              'warehouse_id',
              'Warehouse',
              kind: FieldKind.choice,
              required: true,
              resets: const ['rack_id', 'shelf_id'],
              choices: {
                '': 'Choose warehouse',
                for (final wh in warehouses) wh.id: wh.name,
              },
            ),
            const AdminField(
              'delta_qty',
              'Quantity delta',
              kind: FieldKind.decimal,
              signed: true,
              places: 3,
              required: true,
            ),
            const AdminField(
              'note',
              'Adjustment note',
              kind: FieldKind.multiline,
              maxLength: 500,
            ),
          ],
          seed: const {'rack_id': '', 'shelf_id': ''},
          input: (v) => AdjustmentInput(
            productId: v.text('product_id'),
            warehouseId: v.text('warehouse_id'),
            delta: v.text('delta_qty'),
            rackId: v.text('rack_id'),
            shelfId: v.text('shelf_id'),
            note: v.text('note'),
          ),
          extra: (context, ref, form) {
            final wh = form.values.text('warehouse_id');
            final rack = form.values.text('rack_id');
            if (wh.isEmpty) return const SizedBox.shrink();
            return Column(
              children: [
                QueryPanel(
                  query: racksQuery,
                  argument: wh,
                  builder: (rows) => DropdownButtonFormField<String>(
                    key: ValueKey('rack:$wh:$rack'),
                    initialValue: rows.any((r) => r.id == rack) ? rack : '',
                    isExpanded: true,
                    itemHeight: null,
                    decoration: const InputDecoration(
                      labelText: 'Rack (optional)',
                    ),
                    items: [
                      const DropdownMenuItem(value: '', child: Text('No rack')),
                      for (final row in rows)
                        DropdownMenuItem(
                          value: row.id,
                          child: Text('${row.code} / ${row.label}'),
                        ),
                    ],
                    onChanged: form.locked
                        ? null
                        : (value) {
                            form.set('rack_id', value);
                            form.set('shelf_id', '');
                          },
                  ),
                ),
                if (rack.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    child: QueryPanel(
                      query: shelvesQuery,
                      argument: (warehouseId: wh, rackId: rack),
                      builder: (rows) => DropdownButtonFormField<String>(
                        key: ValueKey(
                          'shelf:$rack:${form.values.text('shelf_id')}',
                        ),
                        initialValue:
                            rows.any(
                              (s) => s.id == form.values.text('shelf_id'),
                            )
                            ? form.values.text('shelf_id')
                            : '',
                        isExpanded: true,
                        itemHeight: null,
                        decoration: const InputDecoration(
                          labelText: 'Shelf (optional)',
                        ),
                        items: [
                          const DropdownMenuItem(
                            value: '',
                            child: Text('No shelf'),
                          ),
                          for (final row in rows)
                            DropdownMenuItem(
                              value: row.id,
                              child: Text('${row.code} / ${row.label}'),
                            ),
                        ],
                        onChanged: form.locked
                            ? null
                            : (value) => form.set('shelf_id', value),
                      ),
                    ),
                  ),
              ],
            );
          },
          onSaved: (_) {
            ref.invalidate(inventoryQuery.provider);
            ref.invalidate(inventoryStatsQuery.provider);
            ref.invalidate(movementsQuery.provider);
            context.go('/inventory');
          },
        ),
      ),
    ],
  );
}

class MovementsScreen extends ConsumerWidget {
  const MovementsScreen({this.productId, super.key});
  final String? productId;
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Server movement history / latest 100',
    title: 'Stock movements',
    actions: [
      recordLink(context, '/inventory', 'Inventory'),
      OutlinedButton(
        onPressed: ref.read(movementsQuery.refreshProvider(productId)),
        child: const Text('Refresh'),
      ),
    ],
    children: [
      QueryPanel(
        query: movementsQuery,
        argument: productId,
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty)
              const EmptyNotice('No stock movements were returned.'),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: row.type.replaceAll('_', ' '),
                  lines: {
                    'Quantity': row.quantity.text,
                    'Recorded': row.createdAt.text,
                    'Reference': row.referenceType ?? 'No linked reference',
                    'Note': row.note ?? 'No note',
                  },
                  actions: [
                    recordLink(
                      context,
                      '/products/${row.productId}',
                      'Product detail',
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
