import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_http.dart';

void main() {
  test('scoped queries clear immediately on logout and never reuse an account cache', () async {
    var logins = 0;
    final backend = OfflineBackend((request) {
      if (request.path == '/auth/login') {
        final id = ++logins == 1 ? userAId : userBId;
        return OfflineResponse({
          'user': userJson(id: id),
        }, cookies: sessionCookies(id));
      }
      if (request.path == '/auth/logout') {
        return const OfflineResponse({}, status: 503);
      }
      return OfflineResponse({
        'name': request.cookie.contains(userBId)
            ? 'Account B data'
            : 'Account A data',
      });
    });
    final session = fixtureSession(backend);
    final auth = StateNotifierProvider<SessionController, SessionState>(
      (ref) => session,
    );
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final query = SessionQuery<String, int>(
      sessionProvider: auth,
      load: (session, scope, page, token) async => JsonObject(
        await session.get('/products', scope: scope, cancelToken: token),
      ).string('name'),
    );
    final keep = container.listen(query.provider(1), (_, next) {});
    addTearDown(keep.close);
    expect(container.read(query.provider(1)).asData, isNull);
    expect(backend.requests, isEmpty);
    await session.login('a@offline.test', 'fixture-only');
    expect(
      (await settledQuery(container, query.provider(1))).requireValue,
      'Account A data',
    );
    final oldScope = session.snapshot.key!;
    final logout = session.logout();
    expect(container.read(query.provider(1)).asData, isNull);
    expect(container.read(query.provider(1)).hasError, isTrue);
    await logout;
    await session.login('b@offline.test', 'fixture-only');
    expect(session.snapshot.key, isNot(oldScope));
    expect(container.read(query.provider(1)).asData, isNull);
    expect(
      (await settledQuery(container, query.provider(1))).requireValue,
      'Account B data',
    );
    expect(backend.count('/products'), 2);
  });

  test('superseded query work is cancelled and cannot overwrite a later account result', () async {
    final oldReply = Completer<OfflineResponse>();
    var logins = 0;
    final backend = OfflineBackend((request) {
      if (request.path == '/auth/login') {
        final id = ++logins == 1 ? userAId : userBId;
        return OfflineResponse({
          'user': userJson(id: id),
        }, cookies: sessionCookies(id));
      }
      if (request.path == '/auth/logout') return const OfflineResponse({});
      return request.cookie.contains(userAId)
          ? oldReply.future
          : const OfflineResponse({'name': 'Fresh account'});
    });
    final session = fixtureSession(backend);
    final auth = StateNotifierProvider<SessionController, SessionState>(
      (ref) => session,
    );
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final query = SessionQuery<String, int>(
      sessionProvider: auth,
      load: (session, scope, page, token) async => JsonObject(
        await session.get('/products', scope: scope, cancelToken: token),
      ).string('name'),
    );
    await session.login('a@offline.test', 'fixture-only');
    final keep = container.listen(query.provider(1), (_, next) {});
    addTearDown(keep.close);
    final oldRequest = await backend.requested('/products');
    await session.logout();
    expect(oldRequest.options.cancelToken!.isCancelled, isTrue);
    await session.login('b@offline.test', 'fixture-only');
    expect(
      (await settledQuery(container, query.provider(1))).requireValue,
      'Fresh account',
    );
    oldReply.complete(const OfflineResponse({'name': 'Old account'}));
    await container.pump();
    expect(container.read(query.provider(1)).requireValue, 'Fresh account');
  });

  test('view disposal cancels pending requests and refresh publishes sanitized errors', () async {
    final reply = Completer<OfflineResponse>();
    var failRefresh = false;
    final backend = OfflineBackend((request) {
      if (request.path == '/auth/login') {
        return OfflineResponse({'user': userJson()});
      }
      return failRefresh
          ? const OfflineResponse({'detail': 'untrusted'}, status: 503)
          : reply.future;
    });
    final session = fixtureSession(backend);
    final auth = StateNotifierProvider<SessionController, SessionState>(
      (ref) => session,
    );
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final query = SessionQuery<Object?, int>(
      sessionProvider: auth,
      load: (session, scope, page, token) =>
          session.get('/products', scope: scope, cancelToken: token),
    );
    await session.login('a@offline.test', 'fixture-only');
    final keep = container.listen(query.provider(1), (_, next) {});
    final request = await backend.requested('/products');
    keep.close();
    await container.pump();
    expect(request.options.cancelToken!.isCancelled, isTrue);
    reply.complete(const OfflineResponse({}));
    failRefresh = true;
    final retryKeep = container.listen(query.provider(1), (_, next) {});
    addTearDown(retryKeep.close);
    await container.read(query.refreshProvider(1))();
    final value = await settledQuery(container, query.provider(1));
    expect(value.error, isA<AppFailure>());
    expect(
      AppFailure.safe(value.error!).message.contains('untrusted'),
      isFalse,
    );
  });
}
