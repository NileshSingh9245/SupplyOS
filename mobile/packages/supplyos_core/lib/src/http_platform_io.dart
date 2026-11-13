import 'package:cookie_jar/cookie_jar.dart';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';

import 'api_config.dart';
import 'http_cookies.dart';

SessionCookies configureSession(Dio dio, ApiConfig config) =>
    _NativeCookies(dio, _SessionCookieJar(requireSecure: !config.isDebug));

class _NativeCookies implements SessionCookies {
  _NativeCookies(Dio dio, this.jar) {
    dio.interceptors.add(CookieManager(jar));
  }

  final _SessionCookieJar jar;

  @override
  SessionCookies forkForLogout(Dio dio) {
    final copy = _SessionCookieJar(requireSecure: jar.requireSecure);
    for (final pair in [
      (jar.domainCookies, copy.domainCookies),
      (jar.hostCookies, copy.hostCookies),
    ]) {
      for (final domain in pair.$1.entries) {
        pair.$2[domain.key] = {
          for (final path in domain.value.entries) path.key: {...path.value},
        };
      }
    }
    return _NativeCookies(dio, copy);
  }

  @override
  Future<void> clear() {
    jar.acceptsCookies = false;
    return jar.deleteAll();
  }
}

class _SessionCookieJar extends DefaultCookieJar {
  _SessionCookieJar({required this.requireSecure});

  final bool requireSecure;
  bool acceptsCookies = true;

  @override
  Future<List<Cookie>> loadForRequest(Uri uri) async {
    if (!acceptsCookies) return [];
    // The cached jar's Secure test uses OR. Enforce both protocol and expiry.
    final eligible = <Cookie>{};
    for (final domains in [domainCookies, hostCookies]) {
      for (final paths in domains.values) {
        for (final cookies in paths.values) {
          for (final stored in cookies.values) {
            if (!stored.isExpired() &&
                (!stored.cookie.secure || uri.scheme == 'https')) {
              eligible.add(stored.cookie);
            }
          }
        }
      }
    }
    return (await super.loadForRequest(uri)).where(eligible.contains).toList();
  }

  @override
  Future<void> saveFromResponse(Uri uri, List<Cookie> cookies) async {
    if (!acceptsCookies) return;
    final authCookies = cookies.where((cookie) {
      final domain = cookie.domain?.replaceFirst(RegExp(r'^\.'), '');
      return (cookie.name == 'access_token' ||
              cookie.name == 'refresh_token') &&
          cookie.httpOnly &&
          (!requireSecure || cookie.secure) &&
          (domain == null ||
              domain == uri.host ||
              uri.host.endsWith('.$domain'));
    }).toList();
    await super.saveFromResponse(uri, authCookies);
    if (!acceptsCookies) await deleteAll();
  }
}
