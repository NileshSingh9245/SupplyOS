import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:cookie_jar/cookie_jar.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Central Dio instance for the customer app.
/// Points to `SUPPLYOS_API_BASE` (compile-time) — defaults to same-origin `/api/v1` for web.
final apiProvider = Provider<Dio>((ref) {
  const base = String.fromEnvironment(
    'SUPPLYOS_API_BASE',
    defaultValue: 'https://3e295af5-2bfc-4745-b3a3-3b12451cf1df.preview.emergentagent.com/api/v1',
  );
  final dio = Dio(BaseOptions(
    baseUrl: base,
    connectTimeout: const Duration(seconds: 20),
    receiveTimeout: const Duration(seconds: 30),
    contentType: 'application/json',
    responseType: ResponseType.json,
    validateStatus: (code) => code != null && code < 500,
  ));
  final jar = CookieJar();
  dio.interceptors.add(CookieManager(jar));

  // Refresh interceptor: on 401 (non-auth path), try /auth/refresh once.
  dio.interceptors.add(InterceptorsWrapper(
    onError: (e, handler) async {
      final path = e.requestOptions.path;
      if (e.response?.statusCode == 401 && !path.contains('/auth/')) {
        try {
          await dio.post('/auth/refresh');
          final clone = await dio.fetch(e.requestOptions);
          return handler.resolve(clone);
        } catch (_) {}
      }
      return handler.next(e);
    },
  ));
  return dio;
});
