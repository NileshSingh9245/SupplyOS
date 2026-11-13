import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_config.dart';
import 'failure.dart';
import 'json_contract.dart';
import 'session_transport.dart';

enum SessionPhase {
  checking,
  signedOut,
  signingIn,
  authenticated,
  checkFailed,
  unavailable,
}

enum LogoutOutcome { confirmed, unconfirmed }

class SessionUser {
  const SessionUser({
    required this.id,
    required this.tenantId,
    required this.email,
    required this.fullName,
    required this.role,
  });

  final String id;
  final String tenantId;
  final String email;
  final String fullName;
  final String role;

  factory SessionUser.fromJson(Object? input) {
    final json = JsonObject(input);
    return SessionUser(
      id: json.uuid('id'),
      tenantId: json.uuid('tenant_id'),
      email: json.string('email'),
      fullName: json.string('full_name'),
      role: json.string('role'),
    );
  }

  bool sameIdentity(SessionUser other) =>
      id == other.id && tenantId == other.tenantId && role == other.role;
}

class SessionKey {
  const SessionKey(this.userId, this.tenantId, this.role, this.generation);

  final String userId;
  final String tenantId;
  final String role;
  final int generation;

  @override
  bool operator ==(Object other) =>
      other is SessionKey &&
      other.userId == userId &&
      other.tenantId == tenantId &&
      other.role == role &&
      other.generation == generation;

  @override
  int get hashCode => Object.hash(userId, tenantId, role, generation);
}

class SessionState {
  const SessionState({
    required this.phase,
    required this.generation,
    this.user,
    this.key,
    this.failure,
    this.isLogoutPending = false,
    this.logoutOutcome,
  });

  final SessionPhase phase;
  final int generation;
  final SessionUser? user;
  final SessionKey? key;
  final AppFailure? failure;
  final bool isLogoutPending;
  final LogoutOutcome? logoutOutcome;

  bool get isAuthenticated =>
      phase == SessionPhase.authenticated && key != null;
  bool get isBusy =>
      phase == SessionPhase.checking ||
      phase == SessionPhase.signingIn ||
      isLogoutPending;
}

class _SessionEpoch {
  _SessionEpoch(this.generation, this.transport);

  final int generation;
  final DioSessionTransport transport;
  SessionUser? user;
  SessionKey? key;
  int renewalVersion = 0;
  Future<void>? renewal;
}

final apiConfigProvider = Provider<ApiConfig?>((ref) {
  try {
    return ApiConfig.fromBuildEnvironment();
  } on AppFailure {
    return null;
  }
});

final sessionTransportFactoryProvider = Provider<SessionTransportFactory>(
  (ref) => DioSessionTransport.new,
);

typedef SessionProvider =
    StateNotifierProvider<SessionController, SessionState>;

SessionProvider roleSessionProvider(String role) =>
    StateNotifierProvider<SessionController, SessionState>((ref) {
      final controller = SessionController(
        config: ref.watch(apiConfigProvider),
        expectedRole: role,
        transportFactory: ref.watch(sessionTransportFactoryProvider),
      );
      unawaited(controller.bootstrap());
      return controller;
    });

class SessionController extends StateNotifier<SessionState> {
  SessionController({
    required this.config,
    required this.expectedRole,
    SessionTransportFactory? transportFactory,
  }) : _transportFactory = transportFactory ?? DioSessionTransport.new,
       super(
         SessionState(
           phase: config == null
               ? SessionPhase.unavailable
               : SessionPhase.checking,
           generation: 0,
           failure: config == null
               ? const AppFailure(FailureKind.configuration)
               : null,
         ),
       );

  final ApiConfig? config;
  final String expectedRole;
  final SessionTransportFactory _transportFactory;
  int _generation = 0;
  _SessionEpoch? _epoch;
  bool _hasBootstrapped = false;
  Future<LogoutOutcome>? _logoutBarrier;
  final _revoking = <DioSessionTransport>{};

  SessionState get snapshot => state;

  bool _isCurrent(_SessionEpoch epoch) =>
      mounted && identical(_epoch, epoch) && _generation == epoch.generation;

  void _requireCurrent(_SessionEpoch epoch) {
    if (!_isCurrent(epoch)) throw const AppFailure(FailureKind.superseded);
  }

  void requireScope(SessionKey scope) {
    if (!mounted || !state.isAuthenticated || state.key != scope) {
      throw const AppFailure(FailureKind.superseded);
    }
  }

  /// Recheck after every await: a later renewal may replace this barrier.
  Future<void>? pendingRenewalForScope(SessionKey scope) {
    requireScope(scope);
    final epoch = _epoch;
    if (epoch == null) throw const AppFailure(FailureKind.superseded);
    return _pendingRenewal(epoch);
  }

  Future<void>? _pendingRenewal(_SessionEpoch epoch) {
    _requireCurrent(epoch);
    final scope = epoch.key;
    if (scope != null) requireScope(scope);
    return epoch.renewal;
  }

  _SessionEpoch _begin(SessionPhase phase) {
    if (!mounted) throw const AppFailure(FailureKind.superseded);
    final configuration = config;
    if (configuration == null) {
      throw const AppFailure(FailureKind.configuration);
    }
    _epoch?.transport.dispose();
    _epoch = null;
    state = SessionState(phase: phase, generation: ++_generation);
    try {
      final epoch = _SessionEpoch(
        _generation,
        _transportFactory(configuration),
      );
      _epoch = epoch;
      return epoch;
    } catch (_) {
      state = SessionState(
        phase: SessionPhase.unavailable,
        generation: _generation,
        failure: const AppFailure(FailureKind.configuration),
      );
      throw const AppFailure(FailureKind.configuration);
    }
  }

  void _checkRole(SessionUser user) {
    if (user.role != expectedRole) {
      throw const AppFailure(FailureKind.wrongRole);
    }
  }

  void _authenticate(_SessionEpoch epoch, SessionUser user) {
    _requireCurrent(epoch);
    _checkRole(user);
    epoch.user = user;
    epoch.key = SessionKey(user.id, user.tenantId, user.role, epoch.generation);
    state = SessionState(
      phase: SessionPhase.authenticated,
      generation: epoch.generation,
      user: user,
      key: epoch.key,
    );
  }

  void _endLocally(
    _SessionEpoch epoch,
    AppFailure? failure, {
    bool checkFailed = false,
  }) {
    if (!_isCurrent(epoch)) return;
    _epoch = null;
    epoch.transport.dispose();
    state = SessionState(
      phase: checkFailed ? SessionPhase.checkFailed : SessionPhase.signedOut,
      generation: ++_generation,
      failure: failure,
    );
  }

  Future<void> bootstrap() async {
    if (_hasBootstrapped || config == null || !mounted) return;
    _hasBootstrapped = true;
    final _SessionEpoch epoch;
    try {
      epoch = _begin(SessionPhase.checking);
    } on AppFailure {
      return;
    }
    try {
      final json = await _read(epoch, '/auth/me');
      _authenticate(epoch, SessionUser.fromJson(json));
    } on AppFailure catch (error) {
      if (!_isCurrent(epoch)) return;
      if (error.kind == FailureKind.wrongRole ||
          error.kind == FailureKind.invalidResponse) {
        await _logout(failure: error);
      } else {
        _endLocally(epoch, error, checkFailed: true);
      }
    }
  }

  Future<void> retryBootstrap() async {
    if (!mounted || state.phase != SessionPhase.checkFailed) return;
    _hasBootstrapped = false;
    await bootstrap();
  }

  Future<void> login(String email, String password) async {
    // A delayed bootstrap cannot run after an explicit authentication decision.
    _hasBootstrapped = true;
    final epoch = _begin(SessionPhase.signingIn);
    try {
      // Browser cookies are global: finish older logout responses before login.
      await _logoutBarrier;
      _requireCurrent(epoch);
      final response = await epoch.transport.send(
        'POST',
        '/auth/login',
        data: {'email': email.trim(), 'password': password},
      );
      _requireCurrent(epoch);
      _authenticate(
        epoch,
        SessionUser.fromJson(JsonObject(response).value('user')),
      );
    } on AppFailure catch (error) {
      if (!_isCurrent(epoch)) throw const AppFailure(FailureKind.superseded);
      final failure = error.statusCode == 401
          ? const AppFailure(FailureKind.invalidCredentials, statusCode: 401)
          : error;
      if (failure.kind == FailureKind.wrongRole ||
          failure.kind == FailureKind.invalidResponse) {
        await _logout(failure: failure);
      } else {
        _endLocally(epoch, failure);
      }
      throw failure;
    }
  }

  Future<Object?> get(
    String path, {
    required SessionKey scope,
    Map<String, Object?>? queryParameters,
    CancelToken? cancelToken,
  }) async {
    requireScope(scope);
    final epoch = _epoch!;
    final result = await _read(
      epoch,
      path,
      queryParameters: queryParameters,
      cancelToken: cancelToken,
    );
    Future<void>? renewal;
    while ((renewal = pendingRenewalForScope(scope)) != null) {
      await renewal;
    }
    return result;
  }

  Future<Object?> _read(
    _SessionEpoch epoch,
    String path, {
    Map<String, Object?>? queryParameters,
    CancelToken? cancelToken,
  }) async {
    Future<void>? renewal;
    while ((renewal = _pendingRenewal(epoch)) != null) {
      await renewal;
    }
    final version = epoch.renewalVersion;
    try {
      final result = await epoch.transport.send(
        'GET',
        path,
        queryParameters: queryParameters,
        cancelToken: cancelToken,
      );
      while ((renewal = _pendingRenewal(epoch)) != null) {
        await renewal;
      }
      return result;
    } on AppFailure catch (error) {
      _requireCurrent(epoch);
      if (error.statusCode != 401 ||
          path == '/auth/login' ||
          path == '/auth/refresh' ||
          path == '/auth/logout') {
        rethrow;
      }
    }
    // Skip redundant refreshes, but never skip a newer identity verification.
    if (epoch.renewalVersion == version) await _renewOnce(epoch);
    while ((renewal = _pendingRenewal(epoch)) != null) {
      await renewal;
    }
    try {
      final result = await epoch.transport.send(
        'GET',
        path,
        queryParameters: queryParameters,
        cancelToken: cancelToken,
      );
      while ((renewal = _pendingRenewal(epoch)) != null) {
        await renewal;
      }
      return result;
    } on AppFailure catch (error) {
      if (error.statusCode == 401) {
        _endLocally(epoch, const AppFailure(FailureKind.signedOut));
      }
      rethrow;
    }
  }

  Future<void> _renewOnce(_SessionEpoch epoch) async {
    final existing = epoch.renewal;
    if (existing != null) return existing;
    final renewal = _renew(epoch);
    epoch.renewal = renewal;
    try {
      await renewal;
    } finally {
      if (identical(epoch.renewal, renewal)) epoch.renewal = null;
    }
  }

  Future<void> _renew(_SessionEpoch epoch) async {
    try {
      // The refresh cookie is managed by the transport, not a JSON bearer token.
      await epoch.transport.send('POST', '/auth/refresh');
      _requireCurrent(epoch);
      final identity = epoch.user;
      if (identity != null) {
        // Raw /me deliberately cannot renew recursively.
        final user = SessionUser.fromJson(
          await epoch.transport.send('GET', '/auth/me'),
        );
        _requireCurrent(epoch);
        _checkRole(user);
        if (!identity.sameIdentity(user)) {
          throw const AppFailure(FailureKind.signedOut);
        }
      }
      epoch.renewalVersion++;
    } on AppFailure catch (error) {
      if (!_isCurrent(epoch)) throw const AppFailure(FailureKind.superseded);
      final failure =
          error.kind == FailureKind.wrongRole ||
              error.kind == FailureKind.invalidResponse
          ? error
          : const AppFailure(FailureKind.signedOut);
      _endLocally(epoch, epoch.user == null ? null : failure);
      throw failure;
    }
  }

  Future<LogoutOutcome> logout() => _logout();

  Future<LogoutOutcome> _logout({AppFailure? failure}) {
    if (!mounted) return Future.value(LogoutOutcome.unconfirmed);
    _hasBootstrapped = true;
    final epoch = _epoch;
    _epoch = null;
    final generation = ++_generation;
    state = SessionState(
      phase: SessionPhase.signedOut,
      generation: generation,
      failure: failure,
      isLogoutPending: true,
    );
    final operations = <Future<bool>>[
      if (_logoutBarrier != null)
        _logoutBarrier!.then((outcome) => outcome == LogoutOutcome.confirmed),
    ];
    if (epoch != null) {
      _revoking.add(epoch.transport);
      operations.add(
        epoch.transport.logout().whenComplete(() {
          _revoking.remove(epoch.transport);
        }),
      );
    }
    late final Future<LogoutOutcome> future;
    future = Future.wait(operations).then((confirmed) {
      final outcome = confirmed.isNotEmpty && confirmed.every((value) => value)
          ? LogoutOutcome.confirmed
          : LogoutOutcome.unconfirmed;
      if (mounted && _generation == generation) {
        state = SessionState(
          phase: SessionPhase.signedOut,
          generation: generation,
          failure: failure,
          logoutOutcome: outcome,
        );
      }
      if (identical(_logoutBarrier, future)) _logoutBarrier = null;
      return outcome;
    });
    _logoutBarrier = future;
    return future;
  }

  @override
  void dispose() {
    _epoch?.transport.dispose();
    _epoch = null;
    for (final transport in _revoking.toList()) {
      transport.dispose();
    }
    super.dispose();
  }
}
