import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'intents.dart';
import 'navigation.dart';

final authProvider = adminSessionProvider;
final themeModeProvider = StateProvider<ThemeMode>((ref) => ThemeMode.dark);
final adminRepositoryProvider = Provider<AdminRepository>(
  (ref) => AdminRepository(ref.watch(authProvider.notifier)),
);
final adminIntentsProvider = ChangeNotifierProvider<AdminIntents>(
  (ref) => AdminIntents(ref.watch(authProvider.notifier)),
);

class AdminRepository {
  const AdminRepository(this.session);
  final SessionController session;

  Future<T> read<T>(
    String path,
    SessionKey scope,
    CancelToken token,
    FutureOr<T> Function(Object?) decode, {
    Map<String, Object?>? parameters,
  }) async {
    requireRoles(scope, adminRoles);
    final response = await session.get(
      path,
      scope: scope,
      cancelToken: token,
      queryParameters: parameters,
    );
    Future<void>? renewal;
    while ((renewal = session.pendingRenewalForScope(scope)) != null) {
      await renewal;
    }
    final value = await decode(response);
    while ((renewal = session.pendingRenewalForScope(scope)) != null) {
      await renewal;
    }
    return value;
  }
}
