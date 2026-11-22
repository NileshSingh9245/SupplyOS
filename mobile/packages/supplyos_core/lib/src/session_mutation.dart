import 'dart:math';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'failure.dart';
import 'mutation_request.dart';
import 'session.dart';

enum MutationPhase {
  ready,
  sending,
  reconciling,
  succeeded,
  rejected,
  uncertain,
  invalidated,
}

class MutationState<T> {
  const MutationState({
    required this.phase,
    this.request,
    this.response,
    this.failure,
  });

  final MutationPhase phase;
  final MutationRequest<T>? request;
  final MutationResponse<T>? response;
  final AppFailure? failure;

  bool get isBusy =>
      phase == MutationPhase.sending || phase == MutationPhase.reconciling;
  bool get canRetry =>
      phase == MutationPhase.uncertain && request?.idempotencyKey != null;
}

enum ReconciliationOutcome { unresolved, applied, notApplied }

/// Only an authoritative, original-key/request-bound lookup can confirm absence.
class MutationReconciliation {
  const MutationReconciliation.unresolved()
    : outcome = ReconciliationOutcome.unresolved,
      statusCode = null,
      body = null;
  const MutationReconciliation.notApplied()
    : outcome = ReconciliationOutcome.notApplied,
      statusCode = null,
      body = null;
  const MutationReconciliation.applied({
    required this.statusCode,
    required this.body,
  }) : outcome = ReconciliationOutcome.applied;

  final ReconciliationOutcome outcome;
  final int? statusCode;
  final Object? body;
}

/// Retain this intent owner until resolved. This is not durable/offline storage.
class SessionMutation<Q, T> extends StateNotifier<MutationState<T>> {
  SessionMutation({required SessionController session, required this.endpoint})
    : _session = session,
      super(MutationState<T>(phase: MutationPhase.ready)) {
    _removeSessionListener = session.addListener((next) {
      if (mounted &&
          state.request != null &&
          next.key != state.request!.scope) {
        _token?.cancel('Session ended');
        state = MutationState<T>(phase: MutationPhase.invalidated);
      }
    }, fireImmediately: false);
  }

  final SessionController _session;
  final JsonMutationEndpoint<Q, T> endpoint;
  late final void Function() _removeSessionListener;
  CancelToken? _token;

  MutationState<T> get snapshot => state;

  Future<MutationResponse<T>> submit(Q input, {String? idempotencyKey}) {
    _requireAvailable();
    final scope = _session.snapshot.key;
    if (scope == null) throw const AppFailure(FailureKind.signedOut);
    final request = endpoint.createRequest(
      input,
      scope: scope,
      idempotencyKey:
          idempotencyKey ?? (endpoint.supportsIdempotency ? _newKey() : null),
    );
    _session.requireScope(scope);
    return _dispatch(request, wasUncertain: false);
  }

  Future<MutationResponse<T>> retry() {
    if (!mounted) throw const AppFailure(FailureKind.superseded);
    if (state.phase != MutationPhase.uncertain) {
      throw const AppFailure(FailureKind.intentPending);
    }
    final request = state.request!;
    _session.requireScope(request.scope);
    if (request.idempotencyKey == null) {
      throw const AppFailure(FailureKind.retryUnsafe);
    }
    return _dispatch(request, wasUncertain: true);
  }

  Future<MutationResponse<T>> _dispatch(
    MutationRequest<T> request, {
    required bool wasUncertain,
  }) async {
    final token = _token = CancelToken();
    state = MutationState<T>(phase: MutationPhase.sending, request: request);
    try {
      final response = await _session.mutate(request, cancelToken: token);
      Future<void>? renewal;
      while ((renewal = _pendingRenewal(request)) != null) {
        await renewal;
      }
      state = MutationState<T>(
        phase: MutationPhase.succeeded,
        request: request,
        response: response,
      );
      return response;
    } catch (error) {
      Future<void>? renewal;
      while ((renewal = _pendingRenewal(request)) != null) {
        await renewal;
      }
      final safe = AppFailure.safe(error);
      // A rejection of a replay does not prove an earlier lost attempt failed.
      final failure = wasUncertain ? safe.asUncertain() : safe;
      state = MutationState<T>(
        phase: failure.isOutcomeUncertain
            ? MutationPhase.uncertain
            : MutationPhase.rejected,
        request: request,
        failure: failure,
      );
      throw failure;
    } finally {
      if (identical(_token, token)) _token = null;
    }
  }

  Future<MutationResponse<T>?> reconcile(
    Future<MutationReconciliation> Function(MutationRequest<T>, CancelToken)
    lookup,
  ) async {
    if (!mounted) throw const AppFailure(FailureKind.superseded);
    if (state.phase != MutationPhase.uncertain) {
      throw const AppFailure(FailureKind.intentPending);
    }
    final request = state.request!;
    _session.requireScope(request.scope);
    final token = _token = CancelToken();
    state = MutationState<T>(
      phase: MutationPhase.reconciling,
      request: request,
    );
    try {
      Future<void>? renewal;
      while ((renewal = _pendingRenewal(request)) != null) {
        await renewal;
      }
      final outcome = await lookup(request, token);
      while ((renewal = _pendingRenewal(request)) != null) {
        await renewal;
      }
      if (outcome.outcome == ReconciliationOutcome.applied) {
        final response = await request.decodeResponse(
          outcome.statusCode ?? 0,
          outcome.body,
        );
        while ((renewal = _pendingRenewal(request)) != null) {
          await renewal;
        }
        state = MutationState<T>(
          phase: MutationPhase.succeeded,
          request: request,
          response: response,
        );
        return response;
      }
      state = MutationState<T>(
        phase: outcome.outcome == ReconciliationOutcome.notApplied
            ? MutationPhase.rejected
            : MutationPhase.uncertain,
        request: request,
        failure: outcome.outcome == ReconciliationOutcome.unresolved
            ? const AppFailure(
                FailureKind.invalidResponse,
                isOutcomeUncertain: true,
              )
            : null,
      );
      return null;
    } catch (error) {
      Future<void>? renewal;
      while ((renewal = _pendingRenewal(request)) != null) {
        await renewal;
      }
      final failure = AppFailure.safe(error).asUncertain();
      state = MutationState<T>(
        phase: MutationPhase.uncertain,
        request: request,
        failure: failure,
      );
      throw failure;
    } finally {
      if (identical(_token, token)) _token = null;
    }
  }

  void _requireAvailable() {
    if (!mounted) throw const AppFailure(FailureKind.superseded);
    if (state.isBusy || state.phase == MutationPhase.uncertain) {
      throw const AppFailure(FailureKind.intentPending);
    }
  }

  Future<void>? _pendingRenewal(MutationRequest<T> request) {
    if (!mounted || !identical(state.request, request)) {
      throw const AppFailure(FailureKind.superseded);
    }
    return _session.pendingRenewalForScope(request.scope);
  }

  @override
  void dispose() {
    _removeSessionListener();
    _token?.cancel('Intent owner closed');
    super.dispose();
  }
}

String _newKey() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes
      .map((value) => value.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}
