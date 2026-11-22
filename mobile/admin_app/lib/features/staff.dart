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

const staffRoles = {managerRole, accountantRole, 'delivery_partner'};

class StaffRecord {
  StaffRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    name = json.string('full_name');
    email = json.string('email');
    phone = json.optionalString('phone');
    role = json.string('role');
    if (!staffRoles.contains(role)) throw invalidResponse;
    active = json.boolean('is_active');
    createdAt = json.timestamp('created_at');
  }
  late final String id, name, email, role;
  late final String? phone;
  late final bool active;
  late final ServerTimestamp createdAt;
}

final staffQuery = SessionQuery<Paginated<StaffRecord>, SearchPage>(
  sessionProvider: authProvider,
  load: (session, scope, arg, token) {
    requireRoles(scope, const {ownerRole});
    return AdminRepository(session).read('/staff', scope, token, (raw) {
      final result = Paginated.fromJson(raw, StaffRecord.new);
      result.requirePage(arg.page, 50);
      return result;
    }, parameters: {'page': arg.page, 'page_size': 50});
  },
);

class StaffInput implements AdminInput {
  const StaffInput(this.name, this.phone, this.role, this.active);
  final String name, phone, role;
  final bool active;
  @override
  Map<String, Object?> toJson() {
    if (!staffRoles.contains(role) || name.trim().length < 2) {
      throw const AppFailure(FailureKind.invalidRequest);
    }
    return {
      'full_name': textInput(name, 200, required: true),
      'phone': optionalText(phone, 30),
      'role': role,
      'is_active': active,
    };
  }
}

AdminCommand<StaffInput, StaffRecord> staffCommand(String id) => AdminCommand(
  slot: 'staff:$id:edit',
  group: 'staff:$id',
  title: 'Save staff access',
  route: '/staff',
  roles: const {ownerRole},
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.patch,
    path: '/staff/${idPath(id)}',
    expectedStatus: 200,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = StaffRecord(raw);
      bindId(value.id, id);
      final body = original.body!;
      if (value.name != body['full_name'] ||
          value.phone != body['phone'] ||
          value.role != body['role'] ||
          value.active != body['is_active']) {
        throw invalidResponse;
      }
      return value;
    },
  ),
);

class RevokedSessions {
  const RevokedSessions(this.currentActorRevoked);
  final bool currentActorRevoked;
}

AdminCommand<NoInput, RevokedSessions> revokeStaffCommand(String id) =>
    AdminCommand(
      slot: 'staff:$id:revoke',
      group: 'staff:$id',
      title: 'Revoke all staff sessions',
      route: '/staff',
      roles: const {ownerRole},
      endpoint: JsonMutationEndpoint(
        method: MutationMethod.post,
        path: '/staff/${idPath(id)}/revoke-sessions',
        expectedStatus: 200,
        encode: (input) => input.toJson(),
        decode: (raw, _) {
          final json = JsonObject(raw);
          if (json.string('message') != 'Staff sessions revoked') {
            throw invalidResponse;
          }
          return RevokedSessions(json.boolean('current_actor_revoked'));
        },
      ),
    );

class StaffScreen extends ConsumerStatefulWidget {
  const StaffScreen({super.key});
  @override
  ConsumerState<StaffScreen> createState() => _StaffScreenState();
}

class _StaffScreenState extends ConsumerState<StaffScreen> {
  int page = 1;
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Owner only / named access',
    title: 'Staff lifecycle',
    actions: [
      OutlinedButton(
        onPressed: ref.read(staffQuery.refreshProvider((page: page, q: ''))),
        child: const Text('Refresh staff'),
      ),
    ],
    children: [
      const CapabilityNotice(
        'Creating a staff login requires a dedicated secret-memory credential transport. No passwords, invitations or generated credentials are sent through shared JSON intents. Owner/customer/self conversion and account deletion are not offered.',
      ),
      QueryPanel(
        query: staffQuery,
        argument: (page: page, q: ''),
        builder: (result) => Column(
          children: [
            if (result.items.isEmpty)
              const EmptyNotice('No staff accounts were returned.'),
            for (final staff in result.items)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: RecordCard(
                  title: staff.name,
                  label: staff.email,
                  status: staff.active ? staff.role : 'inactive',
                  lines: {
                    'Phone': staff.phone ?? 'Not set',
                    'Created': staff.createdAt.text,
                  },
                  actions: [
                    OutlinedButton(
                      onPressed: () => showAccountSheet(
                        context,
                        builder: (sheetContext) => SizedBox(
                          height: MediaQuery.sizeOf(context).height * .9,
                          child: TaskPage(
                            eyebrow: 'Role/activity changes retire sessions',
                            title: staff.name,
                            children: [
                              IntentForm(
                                command: staffCommand(staff.id),
                                fields: [
                                  AdminField(
                                    'full_name',
                                    'Full name',
                                    initial: staff.name,
                                    required: true,
                                  ),
                                  AdminField(
                                    'phone',
                                    'Phone',
                                    initial: staff.phone ?? '',
                                    maxLength: 30,
                                  ),
                                  AdminField(
                                    'role',
                                    'Staff role',
                                    initial: staff.role,
                                    required: true,
                                    kind: FieldKind.choice,
                                    choices: const {
                                      managerRole: 'Warehouse manager',
                                      accountantRole: 'Accountant',
                                      'delivery_partner': 'Delivery partner',
                                    },
                                  ),
                                  AdminField(
                                    'is_active',
                                    'Active account',
                                    initial: staff.active,
                                    kind: FieldKind.boolean,
                                  ),
                                ],
                                input: (v) => StaffInput(
                                  v.text('full_name'),
                                  v.text('phone'),
                                  v.text('role'),
                                  v.boolean('is_active'),
                                ),
                                onSaved: (_) {
                                  ref.read(
                                    staffQuery.refreshProvider((
                                      page: page,
                                      q: '',
                                    )),
                                  )();
                                  Navigator.pop(sheetContext);
                                },
                              ),
                              const SizedBox(height: 24),
                              IntentForm(
                                command: revokeStaffCommand(staff.id),
                                fields: const [],
                                input: (_) => const NoInput(),
                                onSaved: (outcome) {
                                  if (outcome.currentActorRevoked) {
                                    ref.read(authProvider.notifier).logout();
                                  } else {
                                    ref.read(
                                      staffQuery.refreshProvider((
                                        page: page,
                                        q: '',
                                      )),
                                    )();
                                    Navigator.pop(sheetContext);
                                  }
                                },
                              ),
                            ],
                          ),
                        ),
                      ),
                      child: const Text('Manage access'),
                    ),
                  ],
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

Future<FieldChoice?> pickPartner(BuildContext context) {
  final scope = ProviderScope.containerOf(
    context,
    listen: false,
  ).read(authProvider).key;
  if (scope == null) return Future.value(null);
  requireRoles(scope, const {ownerRole});
  return showModalBottomSheet<FieldChoice>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => AccountBoundary(scope: scope, child: const PartnerPicker()),
  );
}

class PartnerPicker extends ConsumerStatefulWidget {
  const PartnerPicker({super.key});
  @override
  ConsumerState<PartnerPicker> createState() => _PartnerPickerState();
}

class _PartnerPickerState extends ConsumerState<PartnerPicker> {
  int page = 1;
  @override
  Widget build(BuildContext context) => SizedBox(
    height: MediaQuery.sizeOf(context).height * .85,
    child: TaskPage(
      eyebrow: 'Owner-only current staff API',
      title: 'Delivery partner',
      children: [
        QueryPanel(
          query: staffQuery,
          argument: (page: page, q: ''),
          builder: (result) {
            final partners = result.items
                .where(
                  (staff) => staff.active && staff.role == 'delivery_partner',
                )
                .toList();
            return Column(
              children: [
                if (partners.isEmpty)
                  const EmptyNotice(
                    'No active delivery partners on this staff page.',
                  ),
                for (final partner in partners)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: RecordCard(
                      title: partner.name,
                      label: partner.email,
                      onTap: () => Navigator.pop(
                        context,
                        FieldChoice(partner.id, partner.name),
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
            );
          },
        ),
      ],
    ),
  );
}
