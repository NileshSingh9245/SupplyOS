import 'failure.dart';

const invalidResponse = AppFailure(FailureKind.invalidResponse);

bool isUuid(String value) => RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
).hasMatch(value);

String shortId(String value) =>
    value.length <= 8 ? value : value.substring(0, 8);

/// Decimal text is opaque server data: never converted, rounded or calculated.
class ServerDecimal {
  const ServerDecimal._(this.text);

  final String text;

  factory ServerDecimal.parse(Object? value) {
    if (value is! String ||
        value.length > 128 ||
        !RegExp(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
            .hasMatch(value)) {
      throw invalidResponse;
    }
    return ServerDecimal._(value);
  }

  @override
  String toString() => text;
}

class ServerTimestamp {
  const ServerTimestamp._(this.text, this.value);

  final String text;
  final DateTime value;

  factory ServerTimestamp.parse(Object? input) {
    if (input is! String) throw invalidResponse;
    final match = RegExp(
      r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$',
    ).firstMatch(input);
    if (match == null) throw invalidResponse;
    final parts = [for (var i = 1; i <= 6; i++) int.parse(match.group(i)!)];
    final checked = DateTime.utc(
      parts[0],
      parts[1],
      parts[2],
      parts[3],
      parts[4],
      parts[5],
    );
    if (parts[0] < 1 ||
        checked.year != parts[0] ||
        checked.month != parts[1] ||
        checked.day != parts[2] ||
        checked.hour != parts[3] ||
        checked.minute != parts[4] ||
        checked.second != parts[5]) {
      throw invalidResponse;
    }
    final zone = match.group(7)!;
    if (zone != 'Z' &&
        (int.parse(zone.substring(1, 3)) > 23 ||
            int.parse(zone.substring(4)) > 59)) {
      throw invalidResponse;
    }
    final parsed = DateTime.tryParse(input);
    if (parsed == null) throw invalidResponse;
    return ServerTimestamp._(input, parsed.toUtc());
  }
}

class ServerDate {
  const ServerDate._(this.text);

  final String text;

  factory ServerDate.parse(Object? input) {
    if (input is! String || !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(input)) {
      throw invalidResponse;
    }
    final parsed = DateTime.tryParse(input);
    if (parsed == null ||
        parsed.year < 1 ||
        parsed.toIso8601String().substring(0, 10) != input) {
      throw invalidResponse;
    }
    return ServerDate._(input);
  }
}

class JsonObject {
  JsonObject(Object? input) {
    if (input is! Map || input.keys.any((Object? key) => key is! String)) {
      throw invalidResponse;
    }
    _data = Map<String, Object?>.from(input);
  }

  late final Map<String, Object?> _data;

  Object? value(String name) => _data[name];

  String string(String name, {bool allowEmpty = false}) {
    final value = _data[name];
    if (value is! String || (!allowEmpty && value.isEmpty)) {
      throw invalidResponse;
    }
    return value;
  }

  String uuid(String name) {
    final value = string(name);
    if (!isUuid(value)) throw invalidResponse;
    return value;
  }

  String? optionalString(String name) =>
      _data[name] == null ? null : string(name, allowEmpty: true);

  String? optionalUuid(String name) => _data[name] == null ? null : uuid(name);

  int integer(String name, {int minimum = 0, int? maximum}) {
    final value = _data[name];
    if (value is! int ||
        value < minimum ||
        (maximum != null && value > maximum)) {
      throw invalidResponse;
    }
    return value;
  }

  bool boolean(String name) {
    final value = _data[name];
    if (value is! bool) throw invalidResponse;
    return value;
  }

  ServerDecimal decimal(String name) => ServerDecimal.parse(_data[name]);

  ServerTimestamp timestamp(String name) => ServerTimestamp.parse(_data[name]);

  ServerTimestamp? optionalTimestamp(String name) =>
      _data[name] == null ? null : timestamp(name);

  ServerDate? optionalDate(String name) =>
      _data[name] == null ? null : ServerDate.parse(_data[name]);

  List<T> list<T>(String name, T Function(Object?) decode) {
    final value = _data[name];
    if (value is! List) throw invalidResponse;
    return List<T>.unmodifiable(value.map((Object? item) => decode(item)));
  }
}

String statusLabel(String value) => switch (value) {
  'pending' => 'Pending',
  'confirmed' => 'Confirmed',
  'reserved' => 'Reserved',
  'picked' => 'Picked',
  'packed' => 'Packed',
  'out_for_delivery' => 'Out for delivery',
  'delivered' => 'Delivered',
  'paid' => 'Paid',
  'completed' => 'Completed',
  'cancelled' => 'Cancelled',
  'unpaid' => 'Unpaid',
  'partially_paid' => 'Partially paid',
  _ => 'Other status: $value',
};
