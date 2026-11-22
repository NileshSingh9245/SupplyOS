import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'package:supplyos_customer/features/auth/auth_provider.dart';
import 'package:supplyos_customer/features/catalog/product.dart';
import 'package:supplyos_customer/features/ordering/ordering_provider.dart';

import '../../packages/supplyos_core/test/support/offline_http.dart';
import 'support/customer_fixtures.dart';
import 'support/workflow_fixtures.dart';
import 'workflow_provider_test.dart' show filledCart;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
      'a healthy held renewal preserves intent but denies cart edits and holds checkout dispatch',
      () async {
    final me = Completer<OfflineResponse>();
    var reads = 0;
    final fixtures = WorkflowFixtures();
    fixtures.intercept = (request) {
      if (request.path == '/renewal-probe') {
        return OfflineResponse({}, status: ++reads == 1 ? 401 : 200);
      }
      if (request.path == '/auth/me') return me.future;
      return null;
    };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final quote = await owner.requestQuote();
    final scope = harness.session.snapshot.key!;
    final renewal = harness.session.get('/renewal-probe', scope: scope);
    await harness.backend.requested('/auth/me');
    expect(
        () => owner.setLine(Product.fromJson(workflowProduct()), '8.000',
            scope: scope),
        throwsA(isA<AppFailure>()));
    final checkout = owner.checkout();
    await harness.container.pump();
    expect(harness.backend.count('/orders/checkout'), 0);
    expect(harness.container.read(customerOrderingProvider).checkout.phase,
        MutationPhase.sending);
    expect(
        harness.container.read(customerOrderingProvider).lastReceipt, isNull);
    me.complete(OfflineResponse(userJson()));
    await renewal;
    final receipt = await checkout;
    expect(receipt.quoteId, quote.id);
    expect(requestKey(await harness.backend.requested('/orders/checkout')),
        quote.id);
    expect(harness.session.snapshot.key, scope);
  });

  test(
      'an accepted 201 stays unpublished until a concurrent renewal verifies the original identity',
      () async {
    final checkoutReply = Completer<OfflineResponse>();
    final me = Completer<OfflineResponse>();
    var reads = 0;
    final fixtures = WorkflowFixtures();
    fixtures.intercept = (request) {
      if (request.path == '/orders/checkout') return checkoutReply.future;
      if (request.path == '/renewal-probe') {
        return OfflineResponse({}, status: ++reads == 1 ? 401 : 200);
      }
      if (request.path == '/auth/me') return me.future;
      return null;
    };
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final quote = await owner.requestQuote();
    final checkout = owner.checkout();
    await harness.backend.requested('/orders/checkout');
    final renewal = harness.session
        .get('/renewal-probe', scope: harness.session.snapshot.key!);
    await harness.backend.requested('/auth/me');
    checkoutReply.complete(OfflineResponse(
        checkoutJson(
            fixtures.quotes[quote.id]!, fixtures.quoteBodies[quote.id]!),
        status: 201));
    await harness.container.pump();
    expect(harness.container.read(customerOrderingProvider).checkout.response,
        isNull);
    expect(
        harness.container.read(customerOrderingProvider).lines.single.quantity,
        '1.250');
    me.complete(OfflineResponse(userJson()));
    await renewal;
    await checkout;
    expect(
        harness.container.read(customerOrderingProvider).lastReceipt!.quoteId,
        quote.id);
    expect(harness.backend.count('/orders/checkout'), 1);
  });

  for (final identity in [
    userJson(role: 'warehouse_manager'),
    userJson(role: 'delivery_partner'),
    userJson(role: 'future_role'),
    userJson(id: userBId),
    userJson(tenantId: tenantBId),
  ].indexed) {
    test(
        'renewal identity or role change ${identity.$1} clears cart and denies a pending original 201',
        () async {
      final checkoutReply = Completer<OfflineResponse>();
      final me = Completer<OfflineResponse>();
      var reads = 0;
      final fixtures = WorkflowFixtures();
      fixtures.intercept = (request) {
        if (request.path == '/orders/checkout') return checkoutReply.future;
        if (request.path == '/renewal-probe') {
          return OfflineResponse({}, status: ++reads == 1 ? 401 : 200);
        }
        if (request.path == '/auth/me') return me.future;
        return null;
      };
      final harness = CustomerHarness(fixtures.handle);
      addTearDown(harness.dispose);
      await harness.login();
      final owner = filledCart(harness);
      final quote = await owner.requestQuote();
      final checkout = owner.checkout();
      final deniedCheckout = expectLater(checkout, throwsA(isA<AppFailure>()));
      await harness.backend.requested('/orders/checkout');
      final renewal = harness.session
          .get('/renewal-probe', scope: harness.session.snapshot.key!);
      final deniedRenewal = expectLater(renewal, throwsA(isA<AppFailure>()));
      await harness.backend.requested('/auth/me');
      checkoutReply.complete(OfflineResponse(
          checkoutJson(
              fixtures.quotes[quote.id]!, fixtures.quoteBodies[quote.id]!),
          status: 201));
      await harness.container.pump();
      expect(harness.container.read(customerOrderingProvider).checkout.response,
          isNull);
      me.complete(OfflineResponse(identity.$2));
      await deniedRenewal;
      await deniedCheckout;
      expect(harness.container.read(authProvider).key, isNull);
      expect(harness.container.read(customerOrderingProvider).lines, isEmpty);
      expect(harness.container.read(customerOrderingProvider).accepted, isNull);
      expect(
          harness.container.read(customerOrderingProvider).lastReceipt, isNull);
      expect(harness.backend.count('/orders/checkout'), 1);
    });
  }

  test(
      'quote 201 pending at logout cannot become an accepted quote in another account',
      () async {
    final reply = Completer<OfflineResponse>();
    final fixtures = WorkflowFixtures()
      ..intercept =
          (request) => request.path == '/order-quotes' ? reply.future : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final quote = owner.requestQuote();
    final denied = expectLater(quote, throwsA(isA<AppFailure>()));
    final request = await harness.backend.requested('/order-quotes');
    await harness.session.logout();
    await harness.login(accountB: true);
    reply.complete(OfflineResponse(
        quoteJson(
            id: requestKey(request),
            body: request.body! as Map<String, Object?>),
        status: 201));
    await denied;
    expect(harness.container.read(customerOrderingProvider).accepted, isNull);
    expect(harness.container.read(customerOrderingProvider).quote.response,
        isNull);
    expect(harness.container.read(customerOrderingProvider).lines, isEmpty);
    await expectLater(owner.recoverQuote(), throwsA(isA<AppFailure>()));
    expect(harness.backend.count('/order-quotes'), 1);
  });

  test(
      'account-scoped preflight pending at logout never sends a quote in the new account',
      () async {
    final profile = Completer<OfflineResponse>();
    final fixtures = WorkflowFixtures()
      ..intercept =
          (request) => request.path == '/customers' ? profile.future : null;
    final harness = CustomerHarness(fixtures.handle);
    addTearDown(harness.dispose);
    await harness.login();
    final owner = filledCart(harness);
    final quote = owner.requestQuote();
    final denied = expectLater(quote, throwsA(isA<AppFailure>()));
    await harness.backend.requested('/customers');
    await harness.session.logout();
    await harness.login(accountB: true);
    profile.complete(OfflineResponse(pageJson([profileJson()])));
    await denied;
    expect(harness.backend.count('/order-quotes'), 0);
    expect(harness.container.read(customerOrderingProvider).scope,
        harness.session.snapshot.key);
    expect(harness.container.read(customerOrderingProvider).accepted, isNull);
  });
}
