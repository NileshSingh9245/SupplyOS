import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'contracts.dart';
import 'navigation.dart';

class AdminCommand<Q extends AdminInput, T> {
  const AdminCommand({
    required this.slot,
    required this.title,
    required this.route,
    required this.roles,
    required this.endpoint,
    this.group,
  });
  final String slot;
  final String title;
  final String route;
  final Set<String> roles;
  final JsonMutationEndpoint<Q, T> endpoint;
  final String? group;
}

class RetainedIntent {
  RetainedIntent({
    required this.slot,
    required this.title,
    required this.route,
    required this.group,
    required this.owner,
    required this.snapshot,
    required this.removeListener,
  });
  final String slot;
  final String title;
  final String route;
  final String group;
  final Object owner;
  final MutationState<Object?> Function() snapshot;
  final void Function() removeListener;
}

/// Account-owned, not route/form-owned. Edits and close never retire uncertainty.
class AdminIntents extends ChangeNotifier {
  AdminIntents(this.session) {
    _scope = session.snapshot.key;
    _removeSessionListener = session.addListener((next) {
      if (!_closed && next.key != _scope) {
        _scope = next.key;
        _clear();
        notifyListeners();
      }
    }, fireImmediately: false);
  }
  final SessionController session;
  final _entries = <String, RetainedIntent>{};
  SessionKey? _scope;
  late final void Function() _removeSessionListener;
  int _revision = 0;
  bool _closed = false;
  int get revision => _revision;

  List<RetainedIntent> get unresolved => List.unmodifiable(
    _entries.values.where((entry) {
      final phase = entry.snapshot().phase;
      return phase == MutationPhase.uncertain ||
          phase == MutationPhase.sending ||
          phase == MutationPhase.reconciling;
    }),
  );

  SessionMutation<Q, T> owner<Q extends AdminInput, T>(
    AdminCommand<Q, T> command,
  ) {
    if (_closed) throw const AppFailure(FailureKind.superseded);
    final scope = session.snapshot.key;
    if (scope == null) throw const AppFailure(FailureKind.signedOut);
    requireRoles(scope, command.roles);
    final existing = _entries[command.slot];
    if (existing != null) {
      final owner = existing.owner;
      if (owner is! SessionMutation<Q, T> ||
          owner.endpoint.path != command.endpoint.path ||
          owner.endpoint.method != command.endpoint.method ||
          owner.endpoint.expectedStatus != command.endpoint.expectedStatus) {
        throw const AppFailure(FailureKind.intentPending);
      }
      return owner;
    }
    final owner = SessionMutation<Q, T>(
      session: session,
      endpoint: command.endpoint,
    );
    final remove = owner.addListener((_) {
      if (!_closed && identical(_entries[command.slot]?.owner, owner)) {
        notifyListeners();
      }
    }, fireImmediately: false);
    _entries[command.slot] = RetainedIntent(
      slot: command.slot,
      title: command.title,
      route: command.route,
      group: command.group ?? command.slot,
      owner: owner,
      snapshot: () => owner.snapshot,
      removeListener: remove,
    );
    return owner;
  }

  Future<MutationResponse<T>> submit<Q extends AdminInput, T>(
    AdminCommand<Q, T> command,
    Q input,
  ) {
    final group = command.group ?? command.slot;
    if (unresolved.any(
      (entry) => entry.slot != command.slot && entry.group == group,
    )) {
      throw const AppFailure(FailureKind.intentPending);
    }
    final current = owner(command);
    return _publish(current.submit(input), session.snapshot.key!);
  }

  Future<MutationResponse<T>> retry<Q extends AdminInput, T>(
    AdminCommand<Q, T> command,
  ) {
    final current = owner(command);
    return _publish(current.retry(), session.snapshot.key!);
  }

  Future<MutationResponse<T>> _publish<T>(
    Future<MutationResponse<T>> attempt,
    SessionKey scope,
  ) async {
    final result = await attempt;
    if (_closed) throw const AppFailure(FailureKind.superseded);
    Future<void>? renewal;
    while ((renewal = session.pendingRenewalForScope(scope)) != null) {
      await renewal;
      if (_closed) throw const AppFailure(FailureKind.superseded);
    }
    _revision++;
    notifyListeners();
    return result;
  }

  void _clear() {
    final entries = _entries.values.toList();
    _entries.clear();
    // Session state notification is iterating its listener list right now.
    // Clear publication immediately, but unlink owners after that iteration.
    scheduleMicrotask(() {
      for (final entry in entries) {
        final owner = entry.owner as SessionMutation;
        if (owner.mounted) {
          entry.removeListener();
          owner.dispose();
        }
      }
    });
  }

  @override
  void dispose() {
    _closed = true;
    _removeSessionListener();
    _clear();
    super.dispose();
  }
}
