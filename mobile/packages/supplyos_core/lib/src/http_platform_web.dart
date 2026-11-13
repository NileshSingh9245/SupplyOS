import 'package:dio/dio.dart';
import 'package:dio_web_adapter/dio_web_adapter.dart';

import 'api_config.dart';
import 'http_cookies.dart';

SessionCookies configureSession(Dio dio, ApiConfig config) =>
    _BrowserCookies(dio);

class _BrowserCookies implements SessionCookies {
  _BrowserCookies(Dio dio) {
    dio.httpClientAdapter = BrowserHttpClientAdapter(
      withCredentials: true,
      enableCORSWarning: false,
    );
  }

  @override
  SessionCookies forkForLogout(Dio dio) => _BrowserCookies(dio);

  @override
  Future<void> clear() async {
    // HttpOnly cookies are browser-owned. Only server logout can delete them.
  }
}
