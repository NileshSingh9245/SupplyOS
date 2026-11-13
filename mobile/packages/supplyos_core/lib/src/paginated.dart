import 'json_contract.dart';

class Paginated<T> {
  const Paginated._({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  final List<T> items;
  final int total;
  final int page;
  final int pageSize;

  bool get hasNext => page * pageSize < total;
  bool get hasPrevious => page > 1;

  factory Paginated.fromJson(Object? input, T Function(Object?) decode) {
    final json = JsonObject(input);
    final total = json.integer('total');
    final page = json.integer('page', minimum: 1);
    final size = json.integer('page_size', minimum: 1, maximum: 500);
    final rawItems = json.value('items');
    if (rawItems is! List<Object?> ||
        rawItems.length > size ||
        rawItems.length > total) {
      throw invalidResponse;
    }
    final items = json.list('items', decode);
    return Paginated._(items: items, total: total, page: page, pageSize: size);
  }

  void requirePage(int requestedPage, int requestedSize) {
    if (page != requestedPage || pageSize != requestedSize) {
      throw invalidResponse;
    }
  }
}
