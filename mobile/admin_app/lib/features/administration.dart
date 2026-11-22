import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../core/contracts.dart';
import '../core/forms.dart';
import '../core/intents.dart';
import '../core/navigation.dart';
import '../core/providers.dart';
import '../core/widgets.dart';
import 'locations.dart';
import 'orders.dart';

class TenantSettings {
  TenantSettings(Object? raw) {
    final json = JsonObject(raw);
    tenantId = json.uuid('tenant_id');
    company = json.string('company_name');
    currency = json.string('currency_code');
    symbol = json.string('currency_symbol');
    locale = json.string('locale');
    final values = JsonObject(json.value('values'));
    belowBase = values.boolean('allow_below_base_price');
    margin = values.decimal('min_margin_pct');
    final keys = json.value('applied_keys');
    applied = keys == null
        ? null
        : jsonList(keys, (value) {
            if (value is! String) throw invalidResponse;
            return value;
          });
  }
  late final String tenantId, company, currency, symbol, locale;
  late final bool belowBase;
  late final ServerDecimal margin;
  late final List<String>? applied;
}

final settingsQuery = SessionQuery<TenantSettings, int>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) =>
      AdminRepository(session).read('/settings', scope, token, (raw) {
        final value = TenantSettings(raw);
        bindId(value.tenantId, scope.tenantId);
        return value;
      }),
);

class SettingsInput implements AdminInput {
  const SettingsInput(this.company, this.belowBase, this.margin);
  final String company, margin;
  final bool belowBase;
  @override
  Map<String, Object?> toJson() => {
    'patch': {
      'company_name': textInput(company, 200, required: true),
      'allow_below_base_price': belowBase,
      'min_margin_pct': decimalInput(margin),
    },
  };
}

final settingsCommand = AdminCommand<SettingsInput, TenantSettings>(
  slot: 'settings:edit',
  title: 'Save supported settings',
  route: '/settings',
  roles: const {ownerRole},
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.patch,
    path: '/settings',
    expectedStatus: 200,
    encode: (input) => input.toJson(),
    decode: (raw, original) {
      final value = TenantSettings(raw);
      bindId(value.tenantId, original.scope.tenantId);
      final patch = original.body!['patch'] as Map<String, Object?>;
      if (value.company != patch['company_name'] ||
          value.belowBase != patch['allow_below_base_price'] ||
          value.applied == null ||
          value.applied!.toSet().length != patch.length ||
          !patch.keys.every(value.applied!.contains)) {
        throw invalidResponse;
      }
      requireDecimalBinding(value.margin, patch['min_margin_pct']);
      return value;
    },
  ),
);

class AlertRecord {
  AlertRecord(Object? raw) {
    final json = JsonObject(raw);
    id = json.uuid('id');
    category = json.string('category');
    severity = json.string('severity');
    title = json.string('title');
    message = json.string('message');
    if (!const {'info', 'warning', 'critical'}.contains(severity)) {
      throw invalidResponse;
    }
    hint = json.optionalString('action_hint');
    resourceType = json.optionalString('resource_type');
    resourceId = json.optionalString('resource_id');
    dismissed = json.boolean('is_dismissed');
    createdAt = json.timestamp('created_at');
  }
  late final String id, category, severity, title, message;
  late final String? hint, resourceType, resourceId;
  late final bool dismissed;
  late final ServerTimestamp createdAt;
}

class AICapability {
  AICapability(Object? raw) {
    final json = JsonObject(raw);
    freeOnly = json.boolean('free_only_mode');
    canSummary = json.boolean('can_request_summary');
    status = json.string('summary_status');
    if (!const {
          'configured',
          'unavailable',
          'held_free_only',
        }.contains(status) ||
        (freeOnly && (canSummary || status != 'held_free_only')) ||
        (!freeOnly && canSummary && status != 'configured') ||
        (!freeOnly && !canSummary && status != 'unavailable')) {
      throw invalidResponse;
    }
  }
  late final bool freeOnly, canSummary;
  late final String status;
}

class AnalysisRecord {
  AnalysisRecord(Object? raw) {
    final json = JsonObject(raw);
    status = json.string('summary_status');
    if (status != 'not_requested') throw invalidResponse;
    final rawCounts = json.value('counts');
    if (rawCounts is! Map) throw invalidResponse;
    final result = <String, int>{};
    for (final entry in rawCounts.entries) {
      if (entry.key is! String ||
          !RegExp(r'^[a-z][a-z0-9_]{0,63}$').hasMatch(entry.key as String) ||
          entry.value is! int ||
          (entry.value as int) < 0) {
        throw invalidResponse;
      }
      result[entry.key as String] = entry.value as int;
    }
    counts = Map.unmodifiable(result);
  }
  late final String status;
  late final Map<String, int> counts;
}

final aiCapabilitiesQuery = SessionQuery<AICapability, int>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) =>
      AdminRepository(session)
          .read('/ai/capabilities', scope, token, AICapability.new),
);
final alertsQuery = SessionQuery<List<AlertRecord>, bool>(
  sessionProvider: authProvider,
  load: (session, scope, include, token) =>
      AdminRepository(session).read('/ai/alerts', scope, token, (raw) {
        final rows = jsonList(raw, AlertRecord.new);
        if (!include && rows.any((row) => row.dismissed)) throw invalidResponse;
        return rows;
      }, parameters: {'include_dismissed': include, 'limit': 100}),
);
final analyzeCommand = AdminCommand<NoInput, AnalysisRecord>(
  slot: 'ai:analyze',
  title: 'Run server rule checks',
  route: '/ai-supervisor',
  roles: const {ownerRole},
  endpoint: JsonMutationEndpoint(
    method: MutationMethod.post,
    path: '/ai/analyze',
    expectedStatus: 200,
    encode: (_) => null,
    decode: (raw, _) => AnalysisRecord(raw),
  ),
);
AdminCommand<NoInput, AlertRecord> dismissAlertCommand(String id) =>
    AdminCommand(
      slot: 'alert:$id:dismiss',
      title: 'Dismiss alert',
      route: '/ai-supervisor',
      roles: const {ownerRole},
      endpoint: JsonMutationEndpoint(
        method: MutationMethod.post,
        path: '/ai/alerts/${idPath(id)}/dismiss',
        expectedStatus: 200,
        encode: (_) => null,
        decode: (raw, _) {
          final value = AlertRecord(raw);
          bindId(value.id, id);
          if (!value.dismissed) throw invalidResponse;
          return value;
        },
      ),
    );

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Control room / current server counters',
    title: 'Overview',
    actions: [
      OutlinedButton(
        onPressed: () {
          ref.read(inventoryStatsQuery.refreshProvider(0))();
          ref.read(orderStatsQuery.refreshProvider(0))();
          ref.read(alertsQuery.refreshProvider(false))();
        },
        child: const Text('Refresh dashboard'),
      ),
    ],
    children: [
      QueryPanel(
        query: settingsQuery,
        argument: 0,
        builder: (settings) => RecordCard(
          title: settings.company,
          lines: {
            'Current tenant currency':
                '${settings.currency} / ${settings.symbol}',
            'Locale metadata': settings.locale,
          },
        ),
      ),
      QueryPanel(
        query: inventoryStatsQuery,
        argument: 0,
        builder: (stats) => RecordCard(title: 'Inventory', lines: stats.lines),
      ),
      QueryPanel(
        query: orderStatsQuery,
        argument: 0,
        builder: (stats) =>
            RecordCard(title: 'Order operations', lines: stats.counters),
      ),
      QueryPanel(
        query: alertsQuery,
        argument: false,
        builder: (alerts) => Column(
          children: [
            if (alerts.isEmpty) const EmptyNotice('No active server alerts.'),
            for (final alert in alerts.take(10))
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: RecordCard(
                  title: alert.title,
                  label: alert.category,
                  status: alert.severity,
                  lines: {'Message': alert.message},
                  actions: [
                    recordLink(context, '/ai-supervisor', 'Open alerts'),
                  ],
                ),
              ),
          ],
        ),
      ),
      const CapabilityNotice(
        'This dashboard shows real inventory/order counters and rule alerts, not fabricated accounting analytics. Revenue trends, attendance, invoices/audit and cross-app event fan-out remain parent/backend work.',
      ),
    ],
  );
}

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => TaskPage(
    eyebrow: 'Owner / persisted and consumed settings',
    title: 'Rules & settings',
    actions: [
      OutlinedButton(
        onPressed: ref.read(settingsQuery.refreshProvider(0)),
        child: const Text('Refresh settings'),
      ),
    ],
    children: [
      QueryPanel(
        query: settingsQuery,
        argument: 0,
        builder: (settings) => Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            RecordCard(
              title: settings.company,
              lines: {
                'Tenant currency metadata':
                    '${settings.currency} / ${settings.symbol}',
                'Locale metadata': settings.locale,
              },
            ),
            const SizedBox(height: 20),
            IntentForm(
              command: settingsCommand,
              fields: [
                AdminField(
                  'company_name',
                  'Company name',
                  initial: settings.company,
                  required: true,
                ),
                AdminField(
                  'allow_below_base_price',
                  'Allow server pricing below product base',
                  initial: settings.belowBase,
                  kind: FieldKind.boolean,
                ),
                AdminField(
                  'min_margin_pct',
                  'Server minimum margin (%)',
                  initial: settings.margin.text,
                  kind: FieldKind.decimal,
                  required: true,
                ),
              ],
              fromBody: (body) =>
                  Map<String, Object?>.from(body['patch'] as Map),
              input: (v) => SettingsInput(
                v.text('company_name'),
                v.boolean('allow_below_base_price'),
                v.text('min_margin_pct'),
              ),
              onSaved: (_) => ref.read(settingsQuery.refreshProvider(0))(),
            ),
          ],
        ),
      ),
      const CapabilityNotice(
        'Only company identity and currently consumed pricing rules are editable here. Currency mutation is withheld while the existing API shadows it; historical currency/invoice snapshots, localization, auto-confirm/reservation expiry, partial/backorders, proof requirements, attendance and recurring AI jobs are not implemented by toggling advertised settings.',
      ),
      const CapabilityNotice(
        'Account passwords, staff credential creation and recipient OTP need separate secret-memory transports. They are not sent in generic JSON mutation intents.',
      ),
    ],
  );
}

class AIScreen extends ConsumerStatefulWidget {
  const AIScreen({super.key});
  @override
  ConsumerState<AIScreen> createState() => _AIScreenState();
}

class _AIScreenState extends ConsumerState<AIScreen> {
  bool include = false;
  @override
  Widget build(BuildContext context) => TaskPage(
    eyebrow: 'Actual rule checks / capability-aware provider gate',
    title: 'AI supervisor',
    actions: [
      OutlinedButton(
        onPressed: () {
          ref.read(alertsQuery.refreshProvider(include))();
          ref.read(aiCapabilitiesQuery.refreshProvider(0))();
        },
        child: const Text('Refresh alerts'),
      ),
    ],
    children: [
      QueryPanel(
        query: aiCapabilitiesQuery,
        argument: 0,
        builder: (capability) => RecordCard(
          title: 'Server capability',
          status: capability.status,
          lines: {
            'Free-only policy': capability.freeOnly
                ? 'Enforced'
                : 'Not enabled',
            'Server summary capability': capability.canSummary
                ? 'Configured'
                : 'Unavailable or held',
            'This client':
                'Rule checks only; no provider request or fake queued summary',
          },
        ),
      ),
      IntentForm(
        command: analyzeCommand,
        fields: const [],
        input: (_) => const NoInput(),
        savedMessage: (result) =>
            'Rule checks confirmed. ${result.counts.entries.map((entry) => '${entry.key.replaceAll('_', ' ')}: ${entry.value}').join('; ')}. No summary requested.',
        onSaved: (_) => ref.read(alertsQuery.refreshProvider(include))(),
      ),
      SwitchListTile(
        title: const Text('Include dismissed alerts'),
        value: include,
        onChanged: (value) => setState(() => include = value),
      ),
      QueryPanel(
        query: alertsQuery,
        argument: include,
        builder: (rows) => Column(
          children: [
            if (rows.isEmpty)
              const EmptyNotice('No rule alerts match this view.'),
            for (final alert in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: RecordCard(
                  title: alert.title,
                  label: '${alert.category} / ${alert.createdAt.text}',
                  status: alert.dismissed ? 'dismissed' : alert.severity,
                  lines: {
                    'Message': alert.message,
                    if (alert.hint != null) 'Server action hint': alert.hint!,
                  },
                  actions: [
                    if (!alert.dismissed)
                      SizedBox(
                        width: double.infinity,
                        child: IntentForm(
                          command: dismissAlertCommand(alert.id),
                          fields: const [],
                          input: (_) => const NoInput(),
                          onSaved: (_) =>
                              ref.read(alertsQuery.refreshProvider(include))(),
                        ),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
      const CapabilityNotice(
        'Recurring jobs, forecasts, route optimization and generative provider transports remain separate approved capabilities. Running rules does not activate a provider, send a summary or constitute cross-app realtime delivery.',
      ),
    ],
  );
}
