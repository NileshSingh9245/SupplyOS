import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/api_client.dart';

class AuthUser {
  final String id;
  final String tenantId;
  final String email;
  final String fullName;
  final String role;
  AuthUser({required this.id, required this.tenantId, required this.email,
    required this.fullName, required this.role});
  factory AuthUser.fromJson(Map<String, dynamic> j) => AuthUser(
    id: j['id'], tenantId: j['tenant_id'], email: j['email'],
    fullName: j['full_name'], role: j['role'],
  );
}

class AuthNotifier extends AsyncNotifier<AuthUser?> {
  @override
  Future<AuthUser?> build() async {
    final dio = ref.read(apiProvider);
    try {
      final r = await dio.get('/auth/me');
      if (r.statusCode == 200) return AuthUser.fromJson(r.data);
    } on DioException { /* not authenticated */ }
    return null;
  }

  Future<void> login(String email, String password) async {
    final dio = ref.read(apiProvider);
    final r = await dio.post('/auth/login', data: {'email': email.trim(), 'password': password});
    if (r.statusCode != 200) throw Exception(r.data['detail']?.toString() ?? 'Login failed');
    final user = AuthUser.fromJson(r.data['user']);
    if (user.role != 'delivery_partner' && user.role != 'super_admin' && user.role != 'warehouse_manager') {
      state = const AsyncValue.data(null);
      try { await dio.post('/auth/logout'); } catch (_) {}
      throw Exception('This account is not authorised for delivery.');
    }
    state = AsyncValue.data(user);
  }

  Future<void> logout() async {
    final dio = ref.read(apiProvider);
    try { await dio.post('/auth/logout'); } catch (_) {}
    state = const AsyncValue.data(null);
  }
}

final authProvider = AsyncNotifierProvider<AuthNotifier, AuthUser?>(AuthNotifier.new);
