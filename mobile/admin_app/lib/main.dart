import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'core/navigation.dart';
import 'core/providers.dart';
import 'core/theme.dart';
import 'core/widgets.dart';
import 'features/administration.dart';
import 'features/catalog.dart';
import 'features/customers.dart';
import 'features/deliveries.dart';
import 'features/finance.dart';
import 'features/locations.dart';
import 'features/orders.dart';
import 'features/pricing.dart';
import 'features/staff.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: SupplyOSAdminApp()));
}

class _RouterRefresh extends ChangeNotifier {
  void changed() => notifyListeners();
}

GoRoute _privateRoute({
  required String path,
  required Widget Function(BuildContext, GoRouterState) builder,
}) => GoRoute(
  path: path,
  pageBuilder: (context, state) {
    final scope = ProviderScope.containerOf(
      context,
      listen: false,
    ).read(authProvider).key;
    return NoTransitionPage(
      key: state.pageKey,
      child: scope == null
          ? const SizedBox.shrink()
          : AccountBoundary(scope: scope, child: builder(context, state)),
    );
  },
);

final adminRouterProvider = Provider<GoRouter>((ref) {
  final refresh = _RouterRefresh();
  ref.listen(authProvider, (_, _) => refresh.changed());
  final router = GoRouter(
    initialLocation: '/session',
    refreshListenable: refresh,
    redirect: (_, state) {
      final session = ref.read(authProvider);
      final path = state.uri.path;
      if (session.phase == SessionPhase.checking) {
        return path == '/session' ? null : '/session';
      }
      if (!session.isAuthenticated) return path == '/login' ? null : '/login';
      final role = session.key!.role;
      if (path == '/session' ||
          path == '/login' ||
          path == '/' ||
          !canVisit(role, path)) {
        return homeFor(role);
      }
      return null;
    },
    routes: [
      GoRoute(
        path: '/session',
        builder: (_, _) =>
            const Scaffold(body: SafeArea(child: LoadingNotice())),
      ),
      GoRoute(
        path: '/login',
        builder: (_, _) => SessionLoginForm(
          sessionProvider: authProvider,
          label: 'SUPPLY / OS // ADMIN',
          title: 'CONTROL\nROOM',
          description: 'Sign in with your owner, warehouse manager or accountant account.',
        ),
      ),
      ShellRoute(
        pageBuilder: (context, state, child) {
          final scope = ProviderScope.containerOf(
            context,
            listen: false,
          ).read(authProvider).key;
          return NoTransitionPage(
            key: state.pageKey,
            child: AdminFrame(
              key: ObjectKey(scope),
              boundScope: scope,
              location: state.uri.path,
              child: child,
            ),
          );
        },
        routes: [
          _privateRoute(
            path: '/dashboard',
            builder: (_, _) => const DashboardScreen(),
          ),
          _privateRoute(
            path: '/products',
            builder: (_, _) => const ProductsScreen(),
          ),
          _privateRoute(
            path: '/products/new',
            builder: (_, _) => const ProductEditScreen(),
          ),
          _privateRoute(
            path: '/products/categories',
            builder: (_, _) => const CategoriesScreen(),
          ),
          _privateRoute(
            path: '/products/categories/:id',
            builder: (_, state) =>
                CategoryDetailScreen(state.pathParameters['id']!),
          ),
          _privateRoute(
            path: '/products/:id/edit',
            builder: (_, state) =>
                ProductEditScreen(id: state.pathParameters['id']!),
          ),
          _privateRoute(
            path: '/products/:id',
            builder: (_, state) =>
                ProductDetailScreen(state.pathParameters['id']!),
          ),
          _privateRoute(
            path: '/warehouses',
            builder: (_, _) => const WarehousesScreen(),
          ),
          _privateRoute(
            path: '/warehouses/new',
            builder: (_, _) => const WarehouseCreateScreen(),
          ),
          _privateRoute(
            path: '/warehouses/:id/racks/:rackId',
            builder: (_, state) => RackDetailScreen(
              state.pathParameters['id']!,
              state.pathParameters['rackId']!,
            ),
          ),
          _privateRoute(
            path: '/warehouses/:id',
            builder: (_, state) =>
                WarehouseDetailScreen(state.pathParameters['id']!),
          ),
          _privateRoute(
            path: '/inventory',
            builder: (_, _) => const InventoryScreen(),
          ),
          _privateRoute(
            path: '/inventory/adjust',
            builder: (_, _) => const AdjustmentScreen(),
          ),
          _privateRoute(
            path: '/inventory/movements',
            builder: (_, state) => MovementsScreen(
              productId: state.uri.queryParameters['product_id'],
            ),
          ),
          _privateRoute(
            path: '/customers',
            builder: (_, _) => const CustomersScreen(),
          ),
          _privateRoute(
            path: '/customers/new',
            builder: (_, _) => const CustomerEditScreen(),
          ),
          _privateRoute(
            path: '/customers/:id/edit',
            builder: (_, state) =>
                CustomerEditScreen(id: state.pathParameters['id']!),
          ),
          _privateRoute(
            path: '/customers/:id',
            builder: (_, state) =>
                CustomerDetailScreen(state.pathParameters['id']!),
          ),
          _privateRoute(
            path: '/pricing',
            builder: (_, state) => PricingScreen(
              customerId: state.uri.queryParameters['customer_id'],
            ),
          ),
          _privateRoute(path: '/staff', builder: (_, _) => const StaffScreen()),
          _privateRoute(
            path: '/orders',
            builder: (_, _) => const OrdersScreen(),
          ),
          _privateRoute(
            path: '/orders/new',
            builder: (_, _) => const OrderCreateScreen(),
          ),
          _privateRoute(
            path: '/orders/:id',
            builder: (_, state) =>
                OrderDetailScreen(state.pathParameters['id']!),
          ),
          _privateRoute(
            path: '/deliveries',
            builder: (_, state) => DeliveriesScreen(
              orderId: state.uri.queryParameters['order_id'],
            ),
          ),
          _privateRoute(
            path: '/deliveries/:id',
            builder: (_, state) =>
                DeliveryDetailScreen(state.pathParameters['id']!),
          ),
          _privateRoute(
            path: '/finance',
            builder: (_, _) => const FinanceScreen(),
          ),
          _privateRoute(
            path: '/settings',
            builder: (_, _) => const SettingsScreen(),
          ),
          _privateRoute(
            path: '/ai-supervisor',
            builder: (_, _) => const AIScreen(),
          ),
          _privateRoute(
            path: '/intents',
            builder: (_, _) => const IntentsScreen(),
          ),
        ],
      ),
    ],
    errorBuilder: (_, _) =>
        const Scaffold(body: Center(child: Text('This route is unavailable.'))),
  );
  ref.onDispose(() {
    router.dispose();
    refresh.dispose();
  });
  return router;
});

class SupplyOSAdminApp extends ConsumerWidget {
  const SupplyOSAdminApp({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => MaterialApp.router(
    title: 'SupplyOS Admin',
    debugShowCheckedModeBanner: false,
    theme: adminTheme(Brightness.light),
    darkTheme: adminTheme(Brightness.dark),
    themeMode: ref.watch(themeModeProvider),
    routerConfig: ref.watch(adminRouterProvider),
  );
}

class AdminFrame extends ConsumerWidget {
  const AdminFrame({
    required this.location,
    required this.child,
    required this.boundScope,
    super.key,
  });
  final String location;
  final Widget child;
  final SessionKey? boundScope;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(authProvider);
    if (session.key == null ||
        !identical(session.key, boundScope) ||
        !canVisit(session.key!.role, location)) {
      return const Scaffold(body: LoadingNotice());
    }
    final scope = session.key!;
    final destinations = destinationsFor(scope.role);
    final wide = MediaQuery.sizeOf(context).width >= 760;
    final registry = ref.watch(adminIntentsProvider);
    final pending = registry.unresolved.length;
    Widget navigation({required bool drawer}) => ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 20, 8, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'SUPPLY / OS',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 8),
              Text(
                scope.role.replaceAll('_', ' ').toUpperCase(),
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ],
          ),
        ),
        for (final destination in destinations)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Material(
              color:
                  location == destination.path ||
                      location.startsWith('${destination.path}/')
                  ? Theme.of(context).colorScheme.primaryContainer
                  : Colors.transparent,
              child: InkWell(
                onTap: () {
                  if (drawer) Navigator.pop(context);
                  context.go(destination.path);
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 16,
                  ),
                  child: Row(
                    children: [
                      Icon(destination.icon),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          destination.label,
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        const Divider(),
        const Padding(
          padding: EdgeInsets.all(12),
          child: Text(
            'Audit, attendance and document modules are omitted until their real APIs exist.',
          ),
        ),
      ],
    );
    return Scaffold(
      key: ObjectKey(scope),
      appBar: AppBar(
        title: const Text(
          'S / OS',
          style: TextStyle(fontWeight: FontWeight.w900),
        ),
        actions: [
          IconButton(
            tooltip: 'Unresolved requests ($pending)',
            onPressed: () => context.go('/intents'),
            icon: Icon(
              Icons.pending_actions,
              color: pending > 0 ? Theme.of(context).colorScheme.primary : null,
            ),
          ),
          IconButton(
            tooltip: 'Switch light/dark theme',
            onPressed: () => ref.read(themeModeProvider.notifier).state =
                ref.read(themeModeProvider) == ThemeMode.dark
                ? ThemeMode.light
                : ThemeMode.dark,
            icon: const Icon(Icons.contrast),
          ),
          IconButton(
            tooltip: 'Sign out and discard this account scope',
            onPressed: () => ref.read(authProvider.notifier).logout(),
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      drawer: wide
          ? null
          : Drawer(child: SafeArea(child: navigation(drawer: true))),
      body: SafeArea(
        child: Row(
          // Paint the nested route first so its BlockSemantics cannot hide nav.
          textDirection: TextDirection.rtl,
          children: [
            Expanded(
              child: Column(
                verticalDirection: VerticalDirection.up,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    child: KeyedSubtree(key: ObjectKey(scope), child: child),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
                    child: Wrap(
                      spacing: 16,
                      runSpacing: 6,
                      children: [
                        Text(
                          scope.role.replaceAll('_', ' ').toUpperCase(),
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                        Text(
                          session.user!.email,
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            if (wide)
              Semantics(
                container: true,
                explicitChildNodes: true,
                label: 'Admin navigation rail',
                child: SizedBox(
                  width: 220,
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      border: Border(
                        right: BorderSide(
                          color: Theme.of(context).colorScheme.outlineVariant,
                        ),
                      ),
                    ),
                    child: navigation(drawer: false),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class IntentsScreen extends ConsumerWidget {
  const IntentsScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final entries = ref.watch(adminIntentsProvider).unresolved;
    return TaskPage(
      eyebrow: 'Account-owned request memory / not offline sync',
      title: 'Unresolved requests',
      children: [
        const CapabilityNotice(
          'Requests remain frozen across form edits, route changes and closes. Only an original same-key replay on an explicitly idempotent endpoint or authoritative reconciliation can resolve uncertainty. There is no durable/encrypted outbox or proof that an absent list row means a request failed.',
        ),
        if (entries.isEmpty)
          const EmptyNotice('No unresolved requests in this account session.'),
        for (final entry in entries)
          RecordCard(
            title: entry.title,
            status: entry.snapshot().phase.name,
            actions: [
              recordLink(context, entry.route, 'Open original workflow'),
            ],
          ),
      ],
    );
  }
}
