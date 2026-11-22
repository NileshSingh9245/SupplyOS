import 'package:flutter/foundation.dart';

import 'failure.dart';

class ApiConfig {
  const ApiConfig._(this.baseUri, this.isDebug);

  final Uri baseUri;
  final bool isDebug;

  String get baseUrl => baseUri.toString();

  factory ApiConfig.fromBuildEnvironment() => ApiConfig.parse(
    const String.fromEnvironment('SUPPLYOS_API_BASE'),
    isDebug: kDebugMode,
  );

  /// The shipped prefix is v1. A different prefix requires a source review.
  factory ApiConfig.parse(String value, {bool isDebug = false}) {
    const invalid = AppFailure(FailureKind.configuration);
    if (value.isEmpty ||
        value != value.trim() ||
        RegExp(r'[\s\\%@]').hasMatch(value) ||
        RegExp(r'(^|/)\.{1,2}(/|$)').hasMatch(value)) {
      throw invalid;
    }
    final uri = Uri.tryParse(value);
    if (uri == null ||
        !uri.hasAuthority ||
        uri.userInfo.isNotEmpty ||
        uri.authority.contains('@') ||
        uri.hasQuery ||
        uri.hasFragment ||
        uri.host.isEmpty ||
        uri.port < 1 ||
        uri.port > 65535 ||
        (uri.scheme != 'https' && !(isDebug && uri.scheme == 'http'))) {
      throw invalid;
    }
    final path = uri.path.endsWith('/')
        ? uri.path.substring(0, uri.path.length - 1)
        : uri.path;
    if (path != '/api/v1') throw invalid;
    if (!isDebug && !_isPublicHostname(uri.host)) throw invalid;
    return ApiConfig._(uri.replace(path: path), isDebug);
  }

  static bool _isPublicHostname(String host) {
    final name = host.toLowerCase();
    // DNS names only in release/profile; this also rejects alternate IP forms.
    if (!RegExp(r'^[a-z0-9-]+(?:\.[a-z0-9-]+)+$').hasMatch(name) ||
        !RegExp(r'[a-z]').hasMatch(name) ||
        !RegExp(r'^[a-z]{2,63}$').hasMatch(name.split('.').last) ||
        name.length > 253) {
      return false;
    }
    for (final label in name.split('.')) {
      if (label.length > 63 || label.startsWith('-') || label.endsWith('-')) {
        return false;
      }
    }
    const privateSuffixes = [
      'localhost',
      'local',
      'internal',
      'lan',
      'home',
      'home.arpa',
      'corp',
      'intranet',
      'private',
      'onion',
      'localtest.me',
      'lvh.me',
      'localhost.direct',
      'nip.io',
      'sslip.io',
      'test',
      'invalid',
      'example',
      'example.com',
      'example.net',
      'example.org',
    ];
    if (privateSuffixes.any(
      (suffix) => name == suffix || name.endsWith('.$suffix'),
    )) {
      return false;
    }
    return !RegExp(r'(placeholder|your[-]?(api|domain|host)|change[-]?me)')
        .hasMatch(name);
  }
}
