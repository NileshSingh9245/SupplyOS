import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'core/theme.dart';
import 'features/auth/auth_provider.dart';
import 'features/auth/login_screen.dart';
import 'features/route/route_screen.dart';

void main() {
  runApp(const ProviderScope(child: SupplyOSDeliveryApp()));
}

class SupplyOSDeliveryApp extends ConsumerWidget {
  const SupplyOSDeliveryApp({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(
      title: 'SupplyOS Delivery',
      theme: buildDarkTheme(),
      routerConfig: router,
      debugShowCheckedModeBanner: false,
    );
  }
}

final routerProvider = Provider<GoRouter>((ref) {
  final refresh = SessionRouterRefresh();
  ref.listen(authProvider, (_, next) => refresh.refresh());
  final router = GoRouter(
    initialLocation: '/route',
    refreshListenable: refresh,
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      GoRoute(
          path: '/route', builder: (_, state) => const _AuthenticatedRoute()),
    ],
    redirect: (context, state) {
      final isAuthed = ref.read(authProvider).isAuthenticated;
      if (!isAuthed && state.matchedLocation != '/login') return '/login';
      if (isAuthed && state.matchedLocation == '/login') return '/route';
      return null;
    },
  );
  ref.onDispose(() {
    router.dispose();
    refresh.dispose();
  });
  return router;
});

class _AuthenticatedRoute extends ConsumerWidget {
  const _AuthenticatedRoute();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final key = ref.watch(authProvider.select((state) => state.key));
    if (key == null) return const SizedBox.shrink();
    return KeyedSubtree(key: ValueKey(key), child: const RouteScreen());
  }
}
