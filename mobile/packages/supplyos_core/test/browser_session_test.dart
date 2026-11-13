import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/browser_probe_stub.dart'
    if (dart.library.js_interop) 'support/browser_probe_web.dart';
import 'support/offline_http.dart';

void main() {
  test('platform-neutral session transport does not add Origin/Fetch/bearer headers', () async {
    final backend = OfflineBackend(
      (request) => request.path == '/auth/login'
          ? OfflineResponse({'user': userJson()})
          : const OfflineResponse({}),
    );
    final session = fixtureSession(backend);
    addTearDown(session.dispose);
    await session.login('fixture@offline.test', 'fixture-password');
    await session.get('/orders', scope: session.snapshot.key!);
    final headers = backend.requests.last.options.headers.keys
        .map((key) => key.toLowerCase())
        .toSet();
    expect(headers.contains('origin'), isFalse);
    expect(headers.contains('referer'), isFalse);
    expect(headers.contains('authorization'), isFalse);
    expect(headers.any((key) => key.startsWith('sec-fetch-')), isFalse);
    await session.logout();
    expect(session.snapshot.key, isNull);
  });

  if (kIsWeb) {
    test('browser adapter explicitly enables credentials without a script cookie manager', () {
      expect(browserCredentialsEnabled(), isTrue);
    });
  }
}
