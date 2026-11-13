import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'failure.dart';
import 'session.dart';

class _QueryKey<A> {
  const _QueryKey(this.scope, this.argument);

  final SessionKey scope;
  final A argument;

  @override
  bool operator ==(Object other) =>
      other is _QueryKey<A> &&
      other.scope == scope &&
      other.argument == argument;

  @override
  int get hashCode => Object.hash(scope, argument);
}

/// No previous account value is carried across an auth-dependent async reload.
class SessionQuery<T, A> {
  SessionQuery({
    required SessionProvider sessionProvider,
    required Future<T> Function(
      SessionController session,
      SessionKey scope,
      A argument,
      CancelToken token,
    )
    load,
  }) {
    final scoped = FutureProvider.autoDispose.family<T, _QueryKey<A>>((
      ref,
      key,
    ) async {
      final session = ref.read(sessionProvider.notifier);
      final token = CancelToken();
      ref.onDispose(() => token.cancel('View closed'));
      ref.listen(sessionProvider.select((state) => state.key), (_, next) {
        if (next != key.scope) token.cancel('Session ended');
      });
      try {
        session.requireScope(key.scope);
        final data = await load(session, key.scope, key.argument, token);
        Future<void>? renewal;
        while ((renewal = session.pendingRenewalForScope(key.scope)) != null) {
          await renewal;
        }
        return data;
      } catch (error) {
        throw AppFailure.safe(error);
      }
    });
    provider = Provider.autoDispose.family<AsyncValue<T>, A>((ref, argument) {
      final scope = ref.watch(sessionProvider.select((state) => state.key));
      if (scope == null) {
        return const AsyncError(
          AppFailure(FailureKind.signedOut),
          StackTrace.empty,
        );
      }
      return ref.watch(scoped(_QueryKey(scope, argument)));
    });
    refreshProvider = Provider.autoDispose.family<Future<void> Function(), A>((
      ref,
      argument,
    ) {
      return () async {
        final scope = ref.read(sessionProvider).key;
        if (scope == null) return;
        final query = scoped(_QueryKey(scope, argument));
        ref.invalidate(query);
        try {
          await ref.read(query.future);
        } on AppFailure {
          // The query publishes the sanitized error for the view to render.
        }
      };
    });
  }

  late final AutoDisposeProviderFamily<AsyncValue<T>, A> provider;
  late final AutoDisposeProviderFamily<Future<void> Function(), A>
  refreshProvider;
}
