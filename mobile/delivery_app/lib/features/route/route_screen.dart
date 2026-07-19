import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';

final routeProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final dio = ref.read(apiProvider);
  final r = await dio.get('/deliveries/my-route');
  return (r.data as List).cast<Map<String, dynamic>>();
});

class RouteScreen extends ConsumerWidget {
  const RouteScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(routeProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Today\'s Route')),
      body: async.when(
        data: (items) => items.isEmpty
          ? const Center(child: Text('No stops scheduled.\nEnjoy the calm.', textAlign: TextAlign.center))
          : ListView.separated(
              itemCount: items.length,
              separatorBuilder: (_, __) => const Divider(height: 1, color: Color(0xFF2E2E2E)),
              itemBuilder: (_, i) {
                final d = items[i];
                return ListTile(
                  leading: CircleAvatar(
                    backgroundColor: const Color(0xFFD4FF00),
                    foregroundColor: Colors.black,
                    child: Text('${d['priority']}'),
                  ),
                  title: Text('Order ${d['order_id'].toString().substring(0, 8)}'),
                  subtitle: Text('OTP verified: ${d['otp_verified'] == true ? 'yes' : 'no'}'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () {
                    // Detail screen with QR scanner, OTP verify, proof capture, collect payment
                  },
                );
              },
            ),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Failed to load route: $e')),
      ),
    );
  }
}
