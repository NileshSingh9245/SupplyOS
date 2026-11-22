import 'package:dio/dio.dart';

import 'api_config.dart';
import 'failure.dart';
import 'http_cookies.dart';

SessionCookies configureSession(Dio dio, ApiConfig config) =>
    throw const AppFailure(FailureKind.configuration);
