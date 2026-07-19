import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
  final auth = ref.watch(authProvider);
  return GoRouter(
    initialLocation: auth.hasValue && auth.value != null ? '/route' : '/login',
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/route', builder: (_, __) => const RouteScreen()),
    ],
    redirect: (context, state) {
      final isAuthed = auth.hasValue && auth.value != null;
      if (!isAuthed && state.matchedLocation != '/login') return '/login';
      if (isAuthed && state.matchedLocation == '/login') return '/route';
      return null;
    },
  );
});
