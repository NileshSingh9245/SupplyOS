import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'core/theme.dart';
import 'features/auth/auth_provider.dart';
import 'features/auth/login_screen.dart';
import 'features/account/account_screen.dart';
import 'features/catalog/catalog_provider.dart';
import 'features/catalog/catalog_screen.dart';
import 'features/catalog/product_detail_screen.dart';
import 'features/orders/orders_screen.dart';
import 'features/orders/order_detail_screen.dart';
import 'features/orders/order_tracking_screen.dart';
import 'features/orders/orders_provider.dart';
import 'features/ordering/cart_screen.dart';
import 'features/ordering/ordering_provider.dart';
import 'features/ordering/quote_review_screen.dart';

void main() {
  runApp(const ProviderScope(child: SupplyOSCustomerApp()));
}

class SupplyOSCustomerApp extends ConsumerWidget {
  const SupplyOSCustomerApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(
      title: 'SupplyOS',
      theme: buildLightTheme(),
      routerConfig: router,
      debugShowCheckedModeBanner: false,
    );
  }
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = SessionRouterRefresh();
  ref.listen(authProvider, (_, next) => refresh.refresh());
  final router = GoRouter(
    initialLocation: '/catalog',
    refreshListenable: refresh,
    redirect: (context, state) {
      final isAuthed = ref.read(authProvider).isAuthenticated;
      final loggingIn = state.matchedLocation == '/login';
      if (!isAuthed && !loggingIn) return '/login';
      if (isAuthed && loggingIn) return '/catalog';
      return null;
    },
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      ShellRoute(
        builder: (_, state, child) =>
            _CustomerShell(location: state.uri.path, child: child),
        routes: [
          GoRoute(
              path: '/catalog', builder: (_, state) => const CatalogScreen()),
          GoRoute(
              path: '/catalog/:id',
              builder: (_, state) =>
                  ProductDetailScreen(id: state.pathParameters['id']!)),
          GoRoute(path: '/cart', builder: (_, state) => const CartScreen()),
          GoRoute(
              path: '/cart/quote',
              builder: (_, state) => const QuoteReviewScreen()),
          GoRoute(path: '/orders', builder: (_, state) => const OrdersScreen()),
          GoRoute(
              path: '/orders/:id',
              builder: (_, state) =>
                  OrderDetailScreen(id: state.pathParameters['id']!)),
          GoRoute(
              path: '/orders/:id/tracking',
              builder: (_, state) =>
                  OrderTrackingScreen(id: state.pathParameters['id']!)),
          GoRoute(
              path: '/account', builder: (_, state) => const AccountScreen()),
          GoRoute(
              path: '/account/ledger',
              builder: (_, state) => const LedgerScreen()),
          GoRoute(
              path: '/account/payments',
              builder: (_, state) => PaymentsScreen(
                  orderId: state.uri.queryParameters['order_id'])),
        ],
      ),
    ],
  );
  ref.onDispose(() {
    router.dispose();
    refresh.dispose();
  });
  return router;
});

class _CustomerShell extends ConsumerWidget {
  const _CustomerShell({required this.location, required this.child});

  final String location;
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final key = ref.watch(authProvider.select((state) => state.key));
    if (key == null) return const SizedBox.shrink();
    final ordering = ref.watch(customerOrderingProvider);
    ref.watch(catalogFilterProvider(key));
    ref.watch(ordersPageProvider(key));
    ref.watch(orderFilterProvider(key));
    final selectedIndex = location.startsWith('/account')
        ? 3
        : location.startsWith('/orders')
            ? 2
            : location.startsWith('/cart')
                ? 1
                : 0;
    void navigate(int index) => context.go([
          '/catalog',
          ordering.isLocked ? '/cart/quote' : '/cart',
          '/orders',
          '/account',
        ][index]);
    final cartIcon = Badge(
      isLabelVisible: ordering.lines.isNotEmpty || ordering.isLocked,
      label: Text(ordering.isLocked ? '!' : '${ordering.lines.length}'),
      child: const Icon(Icons.shopping_bag_outlined),
    );
    return Scaffold(
      body: LayoutBuilder(builder: (context, constraints) {
        final wide = constraints.maxWidth >= 840;
        return Row(children: [
          if (wide)
            NavigationRail(
              scrollable: true,
              selectedIndex: selectedIndex,
              onDestinationSelected: navigate,
              labelType: NavigationRailLabelType.all,
              destinations: [
                const NavigationRailDestination(
                    icon: Icon(Icons.inventory_2_outlined),
                    label: Text('Catalog')),
                NavigationRailDestination(
                    icon: cartIcon, label: const Text('Cart')),
                const NavigationRailDestination(
                    icon: Icon(Icons.receipt_long_outlined),
                    label: Text('Orders')),
                const NavigationRailDestination(
                    icon: Icon(Icons.person_outline), label: Text('Account')),
              ],
            ),
          Expanded(child: KeyedSubtree(key: ValueKey(key), child: child)),
        ]);
      }),
      bottomNavigationBar: MediaQuery.sizeOf(context).width >= 840
          ? null
          : NavigationBar(
              selectedIndex: selectedIndex,
              onDestinationSelected: navigate,
              destinations: [
                const NavigationDestination(
                    icon: Icon(Icons.inventory_2_outlined), label: 'Catalog'),
                NavigationDestination(icon: cartIcon, label: 'Cart'),
                const NavigationDestination(
                    icon: Icon(Icons.receipt_long_outlined), label: 'Orders'),
                const NavigationDestination(
                    icon: Icon(Icons.person_outline), label: 'Account'),
              ],
            ),
    );
  }
}
