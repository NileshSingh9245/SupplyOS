import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_http.dart';

void main() {
  test(
    'normal status validation rejects failure statuses with sanitized messages',
    () async {
      final backend = OfflineBackend(
        (request) =>
            const OfflineResponse({'detail': 'untrusted'}, status: 401),
      );
      final transport = backend.transport(fixtureConfig());
      addTearDown(transport.dispose);
      await expectLater(
        transport.send('GET', '/orders'),
        throwsA(
          isA<AppFailure>().having((error) => error.statusCode, 'status', 401),
        ),
      );
    },
  );

  test('every request has explicit timeouts and no forged browser or bearer headers', () async {
    final backend = OfflineBackend((request) => const OfflineResponse({}));
    final transport = backend.transport(fixtureConfig());
    addTearDown(transport.dispose);
    await transport.send('GET', '/orders');
    final options = backend.requests.single.options;
    expect(options.uri.scheme, 'https');
    expect(options.uri.host, 'api.supplyos.app');
    expect(options.uri.path, '/api/v1/orders');
    expect(options.connectTimeout, const Duration(seconds: 15));
    expect(options.sendTimeout, const Duration(seconds: 15));
    expect(options.receiveTimeout, const Duration(seconds: 30));
    expect(options.followRedirects, isFalse);
    expect(options.maxRedirects, 0);
    final keys = options.headers.keys.map((key) => key.toLowerCase()).toSet();
    expect(keys.contains('origin'), isFalse);
    expect(keys.contains('referer'), isFalse);
    expect(keys.any((key) => key.startsWith('sec-fetch-')), isFalse);
    expect(keys.contains('authorization'), isFalse);
  });

  test('native cookies are HttpOnly, memory-only and copied only for one server logout', () async {
    final backend = OfflineBackend(
      (request) => request.path == '/auth/login'
          ? OfflineResponse({}, cookies: sessionCookies('account-a'))
          : const OfflineResponse({}),
    );
    final transport = backend.transport(fixtureConfig());
    await transport.send('POST', '/auth/login');
    await transport.send('GET', '/orders');
    expect(
      backend.requests.last.cookie.contains('fixture-access-account-a'),
      isTrue,
    );
    expect(await transport.logout(), isTrue);
    expect(backend.requests.last.path, '/auth/logout');
    expect(
      backend.requests.last.cookie.contains('fixture-refresh-account-a'),
      isTrue,
    );
    await expectLater(
      transport.send('GET', '/orders'),
      throwsA(isA<AppFailure>()),
    );
    final fresh = backend.transport(fixtureConfig());
    addTearDown(fresh.dispose);
    await fresh.send('GET', '/products');
    expect(backend.requests.last.cookie, isEmpty);
  });

  test(
    'expired Secure cookies are never sent despite the cached jar OR check',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? const OfflineResponse(
                {},
                cookies: [
                  'access_token=expired-fixture; Path=/; HttpOnly; Secure; Expires=Wed, 01 Jan 2020 00:00:00 GMT',
                  'refresh_token=expired-fixture; Path=/; HttpOnly; Secure; Max-Age=0',
                ],
              )
            : const OfflineResponse({}),
      );
      final transport = backend.transport(fixtureConfig());
      addTearDown(transport.dispose);
      await transport.send('POST', '/auth/login');
      await transport.send('GET', '/orders');
      expect(backend.requests.last.cookie, isEmpty);
    },
  );

  test(
    'Secure cookies cannot be sent to an explicit HTTP debug origin',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? OfflineResponse({}, cookies: sessionCookies('secure'))
            : const OfflineResponse({}),
      );
      final transport = backend.transport(
        ApiConfig.parse('http://127.0.0.1:8001/api/v1', isDebug: true),
      );
      addTearDown(transport.dispose);
      await transport.send('POST', '/auth/login');
      await transport.send('GET', '/orders');
      expect(backend.requests.last.cookie, isEmpty);
    },
  );

  test(
    'Secure cookies that expire after storage are not sent on later requests',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? const OfflineResponse(
                {},
                cookies: [
                  'access_token=short-lived-fixture; Path=/; HttpOnly; Secure; Max-Age=2',
                  'refresh_token=short-lived-fixture; Path=/; HttpOnly; Secure; Max-Age=2',
                ],
              )
            : const OfflineResponse({}),
      );
      final transport = backend.transport(fixtureConfig());
      addTearDown(transport.dispose);
      await transport.send('POST', '/auth/login');
      await transport.send('GET', '/orders');
      expect(
        backend.requests.last.cookie.contains('short-lived-fixture'),
        isTrue,
      );
      await Future<void>.delayed(const Duration(milliseconds: 2300));
      await transport.send('GET', '/products');
      expect(backend.requests.last.cookie, isEmpty);
    },
  );

  test(
    'release discards non-Secure, script-readable and unrelated cookies',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? const OfflineResponse(
                {},
                cookies: [
                  'access_token=readable-fixture; Path=/; Secure',
                  'refresh_token=insecure-fixture; Path=/; HttpOnly',
                  'unrelated=fixture; Path=/; HttpOnly; Secure',
                ],
              )
            : const OfflineResponse({}),
      );
      final transport = backend.transport(fixtureConfig());
      addTearDown(transport.dispose);
      await transport.send('POST', '/auth/login');
      await transport.send('GET', '/orders');
      expect(backend.requests.last.cookie, isEmpty);
    },
  );

  test(
    'debug allows explicit non-Secure HttpOnly cookies without persistence',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? OfflineResponse(
                {},
                cookies: sessionCookies('debug', secure: false),
              )
            : const OfflineResponse({}),
      );
      final transport = backend.transport(
        ApiConfig.parse('http://127.0.0.1:8001/api/v1', isDebug: true),
      );
      addTearDown(transport.dispose);
      await transport.send('POST', '/auth/login');
      await transport.send('GET', '/orders');
      expect(
        backend.requests.last.cookie.contains('fixture-access-debug'),
        isTrue,
      );
    },
  );

  test(
    'a response redirect is rejected instead of treating it as order JSON',
    () async {
      final backend = OfflineBackend(
        (request) => const OfflineResponse({}, isRedirect: true),
      );
      final transport = backend.transport(fixtureConfig());
      addTearDown(transport.dispose);
      await expectLater(
        transport.send('GET', '/orders'),
        throwsA(isA<AppFailure>()),
      );
    },
  );

  test('absolute, escaped and protocol-relative request paths never reach the adapter', () async {
    final backend = OfflineBackend((request) => const OfflineResponse({}));
    final transport = backend.transport(fixtureConfig());
    addTearDown(transport.dispose);
    for (final path in [
      'https://external.test/orders',
      '//external.test/orders',
      '/orders/../auth/me',
      '/orders?customer_id=fixture',
      '/orders/%2e%2e/auth/me',
    ]) {
      await expectLater(
        transport.send('GET', path),
        throwsA(isA<AppFailure>()),
      );
    }
    expect(backend.requests, isEmpty);
  });

  for (final domain in [
    'foreign.test',
    'api.supplyos.app.foreign.test',
    'supplyos.appx',
  ]) {
    test('foreign cookie domain $domain cannot set application auth cookies', () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? OfflineResponse(
                {},
                cookies: [
                  'access_token=foreign-fixture; Domain=$domain; Path=/; HttpOnly; Secure',
                  'refresh_token=foreign-fixture; Domain=$domain; Path=/; HttpOnly; Secure',
                ],
              )
            : const OfflineResponse({}),
      );
      final transport = backend.transport(fixtureConfig());
      addTearDown(transport.dispose);
      await transport.send('POST', '/auth/login');
      await transport.send('GET', '/orders');
      expect(backend.requests.last.cookie, isEmpty);
    });
  }

  test(
    'cookie paths use exact or slash-delimited matches, not sibling prefixes',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? const OfflineResponse(
                {},
                cookies: [
                  'access_token=order-path-fixture; Path=/api/v1/orders; HttpOnly; Secure',
                  'refresh_token=auth-path-fixture; Path=/api/v1/auth; HttpOnly; Secure',
                ],
              )
            : const OfflineResponse({}),
      );
      final transport = backend.transport(fixtureConfig());
      addTearDown(transport.dispose);
      await transport.send('POST', '/auth/login');
      for (final path in ['/orders', '/orders/$orderAId']) {
        await transport.send('GET', path);
        expect(
          backend.requests.last.cookie.contains('order-path-fixture'),
          isTrue,
        );
        expect(
          backend.requests.last.cookie.contains('auth-path-fixture'),
          isFalse,
        );
      }
      for (final path in ['/products', '/orders-archive', '/authentic']) {
        await transport.send('GET', path);
        expect(backend.requests.last.cookie, isEmpty);
      }
      await transport.send('POST', '/auth/refresh');
      expect(
        backend.requests.last.cookie.contains('auth-path-fixture'),
        isTrue,
      );
      expect(
        backend.requests.last.cookie.contains('order-path-fixture'),
        isFalse,
      );
    },
  );

  test(
    'legitimate parent-domain cookies retain their own API path restrictions',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? const OfflineResponse(
                {},
                cookies: [
                  'access_token=parent-access-fixture; Domain=.supplyos.app; Path=/api/v1; HttpOnly; Secure',
                  'refresh_token=parent-refresh-fixture; Domain=.supplyos.app; Path=/api/v1/auth; HttpOnly; Secure',
                ],
              )
            : const OfflineResponse({}),
      );
      final transport = backend.transport(fixtureConfig());
      addTearDown(transport.dispose);
      await transport.send('POST', '/auth/login');
      await transport.send('GET', '/products');
      expect(
        backend.requests.last.cookie.contains('parent-access-fixture'),
        isTrue,
      );
      expect(
        backend.requests.last.cookie.contains('parent-refresh-fixture'),
        isFalse,
      );
      await transport.send('POST', '/auth/refresh');
      expect(
        backend.requests.last.cookie.contains('parent-access-fixture'),
        isTrue,
      );
      expect(
        backend.requests.last.cookie.contains('parent-refresh-fixture'),
        isTrue,
      );
    },
  );

  test(
    'a separate origin transport never inherits host-only session cookies',
    () async {
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? OfflineResponse({}, cookies: sessionCookies('origin-a'))
            : const OfflineResponse({}),
      );
      final first = backend.transport(fixtureConfig());
      final other = backend.transport(
        ApiConfig.parse('https://other.supplyos.app/api/v1'),
      );
      addTearDown(first.dispose);
      addTearDown(other.dispose);
      await first.send('POST', '/auth/login');
      await first.send('GET', '/orders');
      expect(backend.requests.last.cookie.contains('origin-a'), isTrue);
      await other.send('GET', '/orders');
      expect(backend.requests.last.cookie, isEmpty);
    },
  );
}
