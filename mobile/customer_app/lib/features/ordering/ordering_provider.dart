import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';
import '../account/account.dart';
import '../auth/auth_provider.dart';
import '../catalog/product.dart';
import 'order_quote.dart';

final activeWarehousesQuery = SessionQuery<List<ActiveWarehouse>, void>(
  sessionProvider: authProvider,
  load: (session, scope, _, token) async {
    final rows = serverList(
        await session.get('/warehouses', scope: scope, cancelToken: token),
        ActiveWarehouse.fromJson);
    requireUniqueIds(rows, (row) => row.id);
    return List.unmodifiable(rows.where((row) => row.isActive));
  },
);

final customerClockProvider =
    Provider<DateTime Function()>((ref) => DateTime.now);

// Intents live above routes. Auto-disposal would lose a possibly committed order.
final customerOrderingProvider =
    StateNotifierProvider<CustomerOrdering, OrderingState>((ref) {
  return CustomerOrdering(
    session: ref.read(authProvider.notifier),
    now: ref.read(customerClockProvider),
  );
});

class OrderingState {
  const OrderingState({
    this.scope,
    this.lines = const [],
    this.warehouse,
    this.paymentMode = 'cash',
    this.deliveryAddress = '',
    this.scheduledDeliveryDate = '',
    this.notes = '',
    this.preparing = false,
    this.quote = const MutationState(phase: MutationPhase.ready),
    this.checkout = const MutationState(phase: MutationPhase.ready),
    this.accepted,
    this.lastReceipt,
    this.failure,
  });

  final SessionKey? scope;
  final List<CartLine> lines;
  final ActiveWarehouse? warehouse;
  final String paymentMode;
  final String deliveryAddress;
  final String scheduledDeliveryDate;
  final String notes;
  final bool preparing;
  final MutationState<OrderQuote> quote;
  final MutationState<CheckoutReceipt> checkout;
  final AcceptedQuote? accepted;
  final CheckoutReceipt? lastReceipt;
  final AppFailure? failure;

  bool get isBusy => preparing || quote.isBusy || checkout.isBusy;
  bool get isLocked =>
      isBusy ||
      quote.phase == MutationPhase.uncertain ||
      checkout.phase == MutationPhase.uncertain;

  CartLine? lineFor(String id) {
    for (final line in lines) {
      if (line.productId == id.toLowerCase()) return line;
    }
    return null;
  }
}

class CustomerOrdering extends StateNotifier<OrderingState> {
  CustomerOrdering(
      {required SessionController session, required DateTime Function() now})
      : _session = session,
        _now = now,
        super(OrderingState(scope: session.snapshot.key)) {
    _quoteOwner =
        SessionMutation(session: session, endpoint: orderQuoteEndpoint);
    _removeQuote =
        _quoteOwner.addListener(_publishQuote, fireImmediately: false);
    _removeSession = session.addListener((next) {
      if (next.key != state.scope) {
        final previous = _checkoutOwner;
        final removePrevious = _removeCheckout;
        _checkoutOwner = null;
        _removeCheckout = null;
        _profileId = null;
        state = OrderingState(scope: next.key);
        // Removing session listeners during notification mutates its iteration.
        if (previous != null) {
          scheduleMicrotask(() {
            removePrevious?.call();
            previous.dispose();
          });
        }
      }
    }, fireImmediately: false);
  }

  final SessionController _session;
  final DateTime Function() _now;
  late final SessionMutation<QuoteInput, OrderQuote> _quoteOwner;
  late final void Function() _removeQuote;
  late final void Function() _removeSession;
  SessionMutation<AcceptedQuote, CheckoutReceipt>? _checkoutOwner;
  void Function()? _removeCheckout;
  String? _profileId;

  SessionKey _requireCurrent({SessionKey? scope}) {
    final current = state.scope;
    if (!mounted || current == null || (scope != null && scope != current)) {
      throw const AppFailure(FailureKind.superseded);
    }
    _session.requireScope(current);
    return current;
  }

  void _requireEditable({SessionKey? scope}) {
    final current = _requireCurrent(scope: scope);
    if (state.isLocked || _session.pendingRenewalForScope(current) != null) {
      throw const AppFailure(FailureKind.intentPending);
    }
  }

  void _edit({
    List<CartLine>? lines,
    ActiveWarehouse? warehouse,
    bool replaceWarehouse = false,
    String? paymentMode,
    String? address,
    String? date,
    String? notes,
  }) {
    _removeCheckout?.call();
    _removeCheckout = null;
    _checkoutOwner?.dispose();
    _checkoutOwner = null;
    _profileId = null;
    state = OrderingState(
      scope: state.scope,
      lines: lines ?? state.lines,
      warehouse: replaceWarehouse ? warehouse : state.warehouse,
      paymentMode: paymentMode ?? state.paymentMode,
      deliveryAddress: address ?? state.deliveryAddress,
      scheduledDeliveryDate: date ?? state.scheduledDeliveryDate,
      notes: notes ?? state.notes,
      lastReceipt: state.lastReceipt,
    );
  }

  void setLine(Product product, String quantity, {required SessionKey scope}) {
    _requireEditable(scope: scope);
    final line = CartLine(product: product, quantity: quantity);
    final lines = [...state.lines];
    final index = lines.indexWhere((item) => item.productId == line.productId);
    if (index < 0) {
      if (lines.length >= 200) throw const AppFailure(FailureKind.validation);
      lines.add(line);
    } else {
      if (lines[index].quantity == quantity &&
          identical(lines[index].product, product)) {
        return;
      }
      lines[index] = line;
    }
    _edit(lines: List.unmodifiable(lines));
  }

  void removeLine(String productId, {required SessionKey scope}) {
    _requireEditable(scope: scope);
    _edit(
        lines: List.unmodifiable(state.lines
            .where((line) => line.productId != productId.toLowerCase())));
  }

  void chooseWarehouse(ActiveWarehouse? value, {required SessionKey scope}) {
    _requireEditable(scope: scope);
    if (value != null && !value.isActive) {
      throw const AppFailure(FailureKind.validation);
    }
    _edit(warehouse: value, replaceWarehouse: true);
  }

  void choosePaymentMode(String value, {required SessionKey scope}) {
    _requireEditable(scope: scope);
    if (!const {'cash', 'credit'}.contains(value)) {
      throw const AppFailure(FailureKind.validation);
    }
    _edit(paymentMode: value);
  }

  void setDelivery(
      {String? address,
      String? date,
      String? notes,
      required SessionKey scope}) {
    _requireEditable(scope: scope);
    if ((address?.length ?? 0) > 500 ||
        (notes?.length ?? 0) > 500 ||
        (date?.length ?? 0) > 10) {
      throw const AppFailure(FailureKind.validation);
    }
    _edit(address: address, date: date, notes: notes);
  }

  Future<OrderQuote> requestQuote() async {
    _requireEditable();
    final scope = _requireCurrent();
    final warehouse = state.warehouse;
    if (warehouse == null || !warehouse.isActive || state.lines.isEmpty) {
      throw const AppFailure(FailureKind.validation);
    }
    final input = QuoteInput(
      warehouseId: warehouse.id,
      paymentMode: state.paymentMode,
      items: state.lines,
      deliveryAddress:
          state.deliveryAddress.isEmpty ? null : state.deliveryAddress,
      scheduledDeliveryDate: state.scheduledDeliveryDate.isEmpty
          ? null
          : state.scheduledDeliveryDate,
      notes: state.notes.isEmpty ? null : state.notes,
    );
    input.toJson();
    state = _copy(preparing: true, failure: null);
    try {
      final profile = CustomerProfile.parseOwn(await _session.get('/customers',
          scope: scope, queryParameters: {'page': 1, 'page_size': 50}));
      _requireCurrent(scope: scope);
      if (!profile.isActive) throw const AppFailure(FailureKind.forbidden);
      _profileId = profile.id;
      _removeCheckout?.call();
      _removeCheckout = null;
      _checkoutOwner?.dispose();
      _checkoutOwner = null;
      state = OrderingState(
        scope: scope,
        lines: state.lines,
        warehouse: state.warehouse,
        paymentMode: state.paymentMode,
        deliveryAddress: state.deliveryAddress,
        scheduledDeliveryDate: state.scheduledDeliveryDate,
        notes: state.notes,
        lastReceipt: state.lastReceipt,
      );
      return (await _quoteOwner.submit(input)).value;
    } catch (error) {
      if (mounted && state.scope == scope) {
        state = _copy(preparing: false, failure: AppFailure.safe(error));
      }
      rethrow;
    }
  }

  Future<OrderQuote> recoverQuote() async {
    _requireCurrent();
    return (await _quoteOwner.retry()).value;
  }

  Future<CheckoutReceipt> checkout() async {
    final scope = _requireCurrent();
    if (state.isLocked) throw const AppFailure(FailureKind.intentPending);
    final accepted = state.accepted;
    if (accepted == null || accepted.original.scope != scope) {
      throw const AppFailure(FailureKind.validation);
    }
    if (_checkoutOwner?.snapshot.phase == MutationPhase.succeeded) {
      return _checkoutOwner!.snapshot.response!.value;
    }
    if (_checkoutOwner != null ||
        accepted.quote.blockers.isNotEmpty ||
        accepted.quote.expiredAt(_now())) {
      throw const AppFailure(FailureKind.conflict);
    }
    final owner = _checkoutOwner = SessionMutation(
        session: _session, endpoint: checkoutEndpoint(accepted));
    _removeCheckout =
        owner.addListener(_publishCheckout, fireImmediately: false);
    return (await owner.submit(accepted, idempotencyKey: accepted.quote.id))
        .value;
  }

  Future<CheckoutReceipt> recoverCheckout() async {
    _requireCurrent();
    final owner = _checkoutOwner;
    if (owner == null) throw const AppFailure(FailureKind.intentPending);
    return (await owner.retry()).value;
  }

  void _publishQuote(MutationState<OrderQuote> value) {
    if (!mounted || value.request?.scope != state.scope) return;
    final accepted = value.response == null || _profileId == null
        ? null
        : AcceptedQuote(
            quote: value.response!.value,
            original: value.request!,
            customerId: _profileId!);
    state = _copy(
        quote: value, accepted: accepted, preparing: false, failure: null);
  }

  void _publishCheckout(MutationState<CheckoutReceipt> value) {
    if (!mounted || value.request?.scope != state.scope) return;
    if (value.phase == MutationPhase.succeeded) {
      state = OrderingState(
        scope: state.scope,
        quote: state.quote,
        accepted: state.accepted,
        checkout: value,
        lastReceipt: value.response!.value,
      );
    } else {
      state = _copy(checkout: value, failure: null);
    }
  }

  OrderingState _copy({
    bool? preparing,
    MutationState<OrderQuote>? quote,
    MutationState<CheckoutReceipt>? checkout,
    AcceptedQuote? accepted,
    AppFailure? failure,
  }) =>
      OrderingState(
        scope: state.scope,
        lines: state.lines,
        warehouse: state.warehouse,
        paymentMode: state.paymentMode,
        deliveryAddress: state.deliveryAddress,
        scheduledDeliveryDate: state.scheduledDeliveryDate,
        notes: state.notes,
        preparing: preparing ?? state.preparing,
        quote: quote ?? state.quote,
        checkout: checkout ?? state.checkout,
        accepted: quote == null ? state.accepted : accepted,
        lastReceipt: state.lastReceipt,
        failure: failure,
      );

  @override
  void dispose() {
    _removeSession();
    _removeQuote();
    _removeCheckout?.call();
    _quoteOwner.dispose();
    _checkoutOwner?.dispose();
    super.dispose();
  }
}
