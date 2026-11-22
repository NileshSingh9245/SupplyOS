import 'package:dio/dio.dart';

abstract interface class SessionCookies {
  SessionCookies forkForLogout(Dio dio);
  Future<void> clear();
}
