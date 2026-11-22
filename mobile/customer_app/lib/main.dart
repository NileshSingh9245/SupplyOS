import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'core/theme.dart';
import 'features/auth/auth_provider.dart';
import 'features/auth/login_screen.dart';
import 'features/catalog/catalog_screen.dart';
import 'features/orders/orders_screen.dart';
import 'features/orders/order_detail_screen.dart';

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
          GoRoute(path: '/orders', builder: (_, state) => const OrdersScreen()),
          GoRoute(
              path: '/orders/:id',
              builder: (_, state) =>
                  OrderDetailScreen(id: state.pathParameters['id']!)),
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
    return Scaffold(
      body: KeyedSubtree(key: ValueKey(key), child: child),
      bottomNavigationBar: NavigationBar(
        selectedIndex: location.startsWith('/orders') ? 1 : 0,
        onDestinationSelected: (index) =>
            context.go(index == 0 ? '/catalog' : '/orders'),
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.inventory_2_outlined), label: 'Catalog'),
          NavigationDestination(
              icon: Icon(Icons.receipt_long_outlined), label: 'Orders'),
        ],
      ),
    );
  }
}
