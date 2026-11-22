import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

void main() {
  group('release and profile configuration', () {
    for (final base in [
      '',
      '/api/v1',
      'http://api.supplyos.app/api/v1',
      'https://localhost/api/v1',
      'https://api.localhost/api/v1',
      'https://127.0.0.1/api/v1',
      'https://127.1/api/v1',
      'https://2130706433/api/v1',
      'https://0x7f000001/api/v1',
      'https://[::1]/api/v1',
      'https://[::ffff:127.0.0.1]/api/v1',
      'https://10.0.0.1/api/v1',
      'https://172.16.0.1/api/v1',
      'https://192.168.1.1/api/v1',
      'https://169.254.169.254/api/v1',
      'https://backend.local/api/v1',
      'https://backend.internal/api/v1',
      'https://api.home.arpa/api/v1',
      'https://api.corp/api/v1',
      'https://api.intranet/api/v1',
      'https://api.private/api/v1',
      'https://api.localtest.me/api/v1',
      'https://api.lvh.me/api/v1',
      'https://api.localhost.direct/api/v1',
      'https://127.0.0.1.nip.io/api/v1',
      'https://10.0.2.2.sslip.io/api/v1',
      'https://api.example.com/api/v1',
      'https://api.example.org/api/v1',
      'https://api.example.net/api/v1',
      'https://api.invalid/api/v1',
      'https://placeholder.supplyos.app/api/v1',
      'https://your-api.supplyos.app/api/v1',
      'https://api.supplyos.app/api',
      'https://api.supplyos.app/api/v2',
      'https://api.supplyos.app/api/v1/orders',
      'https://api.supplyos.app/api/v1?debug=1',
      'https://api.supplyos.app/api/v1#fragment',
      'https://fixture:fixture@api.supplyos.app/api/v1',
      'https://@api.supplyos.app/api/v1',
      'https://api.supplyos.app/api/v1/../v1',
      'https://api.supplyos.app/api/v1%2f',
      ' https://api.supplyos.app/api/v1',
      'https://api.supplyos.app/api/v1 ',
      'https://api.supplyos.app:0/api/v1',
      'https://api.supplyos.app:65536/api/v1',
      'https://api.supplyos.app\\api\\v1',
    ].indexed) {
      test('rejects unsafe base ${base.$1 + 1} without reflecting it', () {
        expect(() => ApiConfig.parse(base.$2), throwsA(isA<AppFailure>()));
      });
    }

    test(
      'public HTTPS base is explicit and normalizes trailing slash only',
      () {
        final config = ApiConfig.parse('https://api.supplyos.app:443/api/v1/');
        expect(config.baseUri.path, '/api/v1');
        expect(config.baseUri.scheme, 'https');
        expect(config.isDebug, isFalse);
      },
    );

    test('HTTPS on an explicit public nondefault port is supported', () {
      expect(
        ApiConfig.parse('https://api.supplyos.app:8443/api/v1').baseUri.port,
        8443,
      );
    });

    test('configuration errors cannot echo credentials or endpoint text', () {
      try {
        ApiConfig.parse('https://fixture:fixture@api.supplyos.app/api/v1');
        fail('Unsafe configuration was accepted');
      } on AppFailure catch (error) {
        expect(error.toString().contains('fixture'), isFalse);
        expect(error.toString().contains('supplyos.app'), isFalse);
      }
    });
  });

  group('explicit debug development configuration', () {
    for (final base in [
      'http://127.0.0.1:8001/api/v1',
      'http://10.0.2.2:8001/api/v1',
      'http://localhost:8001/api/v1',
      'http://[::1]:8001/api/v1',
    ]) {
      test('allows an explicit development origin $base', () {
        expect(ApiConfig.parse(base, isDebug: true).isDebug, isTrue);
        expect(() => ApiConfig.parse(base), throwsA(isA<AppFailure>()));
      });
    }
    test('debug still has no default or credential-bearing base', () {
      expect(
        () => ApiConfig.parse('', isDebug: true),
        throwsA(isA<AppFailure>()),
      );
      expect(
        () => ApiConfig.parse(
          'http://fixture:fixture@localhost/api/v1',
          isDebug: true,
        ),
        throwsA(isA<AppFailure>()),
      );
    });
  });
}
