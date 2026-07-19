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
    id: j['id'] as String, tenantId: j['tenant_id'] as String,
    email: j['email'] as String, fullName: j['full_name'] as String,
    role: j['role'] as String,
  );
}

class AuthNotifier extends AsyncNotifier<AuthUser?> {
  @override
  Future<AuthUser?> build() async {
    final dio = ref.read(apiProvider);
    try {
      final r = await dio.get('/auth/me');
      if (r.statusCode == 200) return AuthUser.fromJson(r.data as Map<String, dynamic>);
    } on DioException {
      // ignore
    }
    return null;
  }

  Future<void> login(String email, String password) async {
    state = const AsyncValue.loading();
    final dio = ref.read(apiProvider);
    try {
      final r = await dio.post('/auth/login', data: {'email': email.trim(), 'password': password});
      if (r.statusCode == 200) {
        final user = AuthUser.fromJson((r.data['user']) as Map<String, dynamic>);
        state = AsyncValue.data(user);
      } else {
        final detail = r.data is Map ? r.data['detail']?.toString() : 'Login failed';
        throw Exception(detail ?? 'Login failed');
      }
    } catch (e, st) {
      state = AsyncValue.error(e, st);
      rethrow;
    }
  }

  Future<void> registerCustomer({
    required String email, required String password, required String fullName,
    String? phone, String? businessName,
  }) async {
    final dio = ref.read(apiProvider);
    await dio.post('/auth/register-customer', data: {
      'email': email, 'password': password, 'full_name': fullName,
      if (phone != null) 'phone': phone,
      if (businessName != null) 'business_name': businessName,
    });
    await login(email, password);
  }

  Future<void> logout() async {
    final dio = ref.read(apiProvider);
    try { await dio.post('/auth/logout'); } catch (_) {}
    state = const AsyncValue.data(null);
  }
}

final authProvider = AsyncNotifierProvider<AuthNotifier, AuthUser?>(AuthNotifier.new);
