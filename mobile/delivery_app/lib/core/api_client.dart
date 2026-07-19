// Reuses the same pattern as customer_app; see customer_app/lib/core/api_client.dart
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:cookie_jar/cookie_jar.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final apiProvider = Provider<Dio>((ref) {
  const base = String.fromEnvironment(
    'SUPPLYOS_API_BASE',
    defaultValue: 'https://3e295af5-2bfc-4745-b3a3-3b12451cf1df.preview.emergentagent.com/api/v1',
  );
  final dio = Dio(BaseOptions(baseUrl: base, contentType: 'application/json'));
  dio.interceptors.add(CookieManager(CookieJar()));
  return dio;
});
