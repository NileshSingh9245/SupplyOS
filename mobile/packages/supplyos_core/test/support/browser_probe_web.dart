import 'package:dio/dio.dart';
import 'package:dio_web_adapter/dio_web_adapter.dart';
import 'package:supplyos_core/src/http_platform_web.dart';
import 'package:supplyos_core/supplyos_core.dart';

bool browserCredentialsEnabled() {
  final dio = Dio();
  configureSession(dio, ApiConfig.parse('https://api.supplyos.app/api/v1'));
  final adapter = dio.httpClientAdapter;
  final enabled =
      adapter is BrowserHttpClientAdapter &&
      adapter.withCredentials &&
      dio.interceptors.length == 1;
  dio.close(force: true);
  return enabled;
}
