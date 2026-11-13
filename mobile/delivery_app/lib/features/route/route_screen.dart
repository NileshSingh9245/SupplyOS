import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../auth/auth_provider.dart';
import 'route_provider.dart';

class RouteScreen extends ConsumerWidget {
  const RouteScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(authProvider.select((state) => state.key)) == null) {
      return const SizedBox.shrink();
    }
    final async = ref.watch(routeProvider(null));
    final refresh = ref.read(routeQuery.refreshProvider(null));
    return Scaffold(
      appBar: AppBar(title: const Text('Assigned route'), actions: [
        IconButton(
            tooltip: 'Refresh route',
            onPressed: async.isLoading ? null : refresh,
            icon: const Icon(Icons.refresh)),
        SessionLogoutButton(sessionProvider: authProvider),
      ]),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: async.when(
          skipLoadingOnRefresh: false,
          skipLoadingOnReload: false,
          data: (items) => ListView.separated(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(16),
            itemCount: items.isEmpty ? 2 : items.length + 1,
            separatorBuilder: (_, index) => const Divider(height: 1),
            itemBuilder: (_, index) {
              if (index == 0) {
                return const Padding(
                  padding: EdgeInsets.only(bottom: 16),
                  child: Text(
                    'Your incomplete stops for today (UTC), including undated stops. Server priority order.',
                  ),
                );
              }
              if (items.isEmpty) {
                return const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Text('No assigned stops.'),
                );
              }
              final stop = items[index - 1];
              return ListTile(
                leading: CircleAvatar(
                  backgroundColor: const Color(0xFFD4FF00),
                  foregroundColor: Colors.black,
                  child: Text('${stop.priority}'),
                ),
                title: Text('Order ${shortId(stop.orderId)}'),
                subtitle:
                    Text('OTP verified: ${stop.isOtpVerified ? 'yes' : 'no'}'),
              );
            },
          ),
          loading: () => const ReadLoading(),
          error: (error, stack) => ReadFeedback(
            title: 'Unable to load route.',
            message: AppFailure.safe(error).message,
            onRetry: refresh,
          ),
        ),
      ),
    );
  }
}
