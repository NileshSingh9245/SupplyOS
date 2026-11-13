import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_http.dart';

void main() {
  for (final value in [
    '0.00',
    '-0.000',
    '12345678901234567890.1234567890',
    '1E-20',
    '+001.2300',
    '.5000',
    '-42.01',
    '9.',
  ]) {
    test('decimal text is preserved exactly: $value', () {
      expect(ServerDecimal.parse(value).text, value);
      expect(ServerDecimal.parse(value).toString(), value);
    });
  }
  for (final value in <Object?>[
    null,
    0,
    1.25,
    '',
    'NaN',
    'Infinity',
    '-Infinity',
    '1,000.00',
    ' 1.00',
    '1.00 ',
    'abc',
    true,
    {},
    [],
  ].indexed) {
    test('rejects invalid decimal ${value.$1 + 1}', () {
      expect(() => ServerDecimal.parse(value.$2), throwsA(isA<AppFailure>()));
    });
  }

  test(
    'date-only values do not invent an offset or normalize invalid days',
    () {
      expect(ServerDate.parse('2026-11-12').text, '2026-11-12');
      expect(() => ServerDate.parse('2026-02-31'), throwsA(isA<AppFailure>()));
      expect(
        () => ServerDate.parse('2026-11-12T00:00:00Z'),
        throwsA(isA<AppFailure>()),
      );
    },
  );

  test('timestamps retain raw text and compare using UTC', () {
    final first = ServerTimestamp.parse('2026-11-12T09:00:00+05:30');
    final second = ServerTimestamp.parse('2026-11-12T03:30:00Z');
    expect(first.value, second.value);
    expect(first.text, '2026-11-12T09:00:00+05:30');
  });

  for (final value in [
    null,
    'not-a-date',
    '2026-11-12',
    '2026-11-12T03:30:00',
    '2026-02-31T00:00:00Z',
    '2026-11-12T24:00:00Z',
    '2026-11-12T00:00:00+99:99',
  ].indexed) {
    test('malformed timestamp is a sanitized failure ${value.$1 + 1}', () {
      expect(() => ServerTimestamp.parse(value.$2), throwsA(isA<AppFailure>()));
    });
  }

  test('UUID and short identifier guards tolerate short display inputs', () {
    expect(isUuid(orderAId), isTrue);
    expect(isUuid('short'), isFalse);
    expect(shortId(''), '');
    expect(shortId('short'), 'short');
    expect(shortId(orderAId), '55555555');
  });

  test(
    'unknown statuses remain passive text rather than an invented transition',
    () {
      expect(statusLabel('future_hold'), 'Other status: future_hold');
    },
  );

  test('paginated envelope preserves metadata and immutable typed items', () {
    final page = Paginated<String>.fromJson({
      'items': ['one'],
      'total': 51,
      'page': 1,
      'page_size': 50,
    }, (value) => value! as String);
    expect(page.hasNext, isTrue);
    expect(page.hasPrevious, isFalse);
    expect(page.items, ['one']);
    expect(() => page.items.add('two'), throwsUnsupportedError);
    page.requirePage(1, 50);
    expect(() => page.requirePage(2, 50), throwsA(isA<AppFailure>()));
  });

  for (final input in <Object?>[
    null,
    [],
    {'items': null, 'total': 0, 'page': 1, 'page_size': 50},
    {'items': <Object?>[], 'total': '0', 'page': 1, 'page_size': 50},
    {'items': <Object?>[], 'total': -1, 'page': 1, 'page_size': 50},
    {'items': <Object?>[], 'total': 0, 'page': 0, 'page_size': 50},
    {'items': <Object?>[], 'total': 0, 'page': 1, 'page_size': 501},
    {'items': <Object?>[], 'total': 0, 'page': 1, 'page_size': 0},
    {
      'items': [1],
      'total': 0,
      'page': 1,
      'page_size': 50,
    },
    {
      'items': [1, 2],
      'total': 2,
      'page': 1,
      'page_size': 1,
    },
    {'items': <Object?>[], 'total': 0, 'page': 1},
  ].indexed) {
    test('malformed envelope ${input.$1 + 1} is rejected without defaults', () {
      expect(
        () => Paginated<Object?>.fromJson(input.$2, (value) => value),
        throwsA(isA<AppFailure>()),
      );
    });
  }

  test('oversized page items are rejected before decoding untrusted items', () {
    var decoded = 0;
    expect(
      () => Paginated<Object?>.fromJson(
        {
          'items': List<Object?>.filled(501, null),
          'total': 501,
          'page': 1,
          'page_size': 500,
        },
        (value) {
          decoded++;
          return value;
        },
      ),
      throwsA(isA<AppFailure>()),
    );
    expect(decoded, 0);
  });
}
