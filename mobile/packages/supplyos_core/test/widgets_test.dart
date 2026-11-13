import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'support/offline_http.dart';
import 'support/widget_harness.dart';

SessionLoginForm loginForm(SessionProvider provider) => SessionLoginForm(
  sessionProvider: provider,
  label: 'SUPPLYOS / FIXTURE',
  title: 'Online access',
  description: 'Offline fixture test only.',
);

void main() {
  testWidgets(
    'missing API configuration is visible and disables credentials and sign-in',
    (tester) async {
      final auth = roleSessionProvider('customer');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiConfigProvider.overrideWithValue(null)],
          child: MaterialApp(home: loginForm(auth)),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.text(const AppFailure(FailureKind.configuration).message),
        findsOneWidget,
      );
      expect(
        tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed,
        isNull,
      );
      expect(
        tester
            .widgetList<TextFormField>(find.byType(TextFormField))
            .every((field) => field.enabled == false),
        isTrue,
      );
    },
  );

  testWidgets(
    'login shows sanitized errors, clears the password, and disposes controllers',
    (tester) async {
      final backend = OfflineBackend(
        (request) =>
            const OfflineResponse({'detail': 'untrusted-fixture'}, status: 401),
      );
      final session = fixtureSession(backend);
      await tester.runAsync(session.bootstrap);
      final auth = StateNotifierProvider<SessionController, SessionState>(
        (ref) => session,
      );
      final container = ProviderContainer();
      addTearDown(container.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp(home: loginForm(auth)),
        ),
      );
      final fields = find.byType(TextFormField);
      await tester.enterText(fields.at(0), 'fixture@offline.test');
      await tester.enterText(fields.at(1), 'fixture-password');
      final passwordController = tester
          .widget<TextFormField>(fields.at(1))
          .controller!;
      await tester.ensureVisible(find.text('Sign in'));
      await tester.tap(find.text('Sign in'));
      await pumpUntil(
        tester,
        () => session.snapshot.phase == SessionPhase.signedOut,
      );
      await tester.pumpAndSettle();
      expect(
        find.text(const AppFailure(FailureKind.invalidCredentials).message),
        findsOneWidget,
      );
      expect(find.textContaining('untrusted-fixture'), findsNothing);
      expect(passwordController.text, isEmpty);
      await tester.pumpWidget(const SizedBox.shrink());
      expect(() => passwordController.addListener(() {}), throwsFlutterError);
    },
  );

  testWidgets(
    'delayed sign-in failure is mounted-safe after the form is removed',
    (tester) async {
      final reply = Completer<OfflineResponse>();
      final backend = OfflineBackend(
        (request) => request.path == '/auth/login'
            ? reply.future
            : const OfflineResponse({}, status: 401),
      );
      final session = fixtureSession(backend);
      await tester.runAsync(session.bootstrap);
      final auth = StateNotifierProvider<SessionController, SessionState>(
        (ref) => session,
      );
      final container = ProviderContainer();
      addTearDown(container.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp(home: loginForm(auth)),
        ),
      );
      await tester.enterText(
        find.byType(TextFormField).at(0),
        'fixture@offline.test',
      );
      await tester.enterText(
        find.byType(TextFormField).at(1),
        'fixture-password',
      );
      await tester.ensureVisible(find.text('Sign in'));
      await tester.tap(find.text('Sign in'));
      await pumpUntil(tester, () => backend.count('/auth/login') == 1);
      await tester.pumpWidget(const SizedBox.shrink());
      reply.complete(const OfflineResponse({}, status: 401));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'the shared login form remains scrollable on small screens with large text',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final session = SessionController(
        config: null,
        expectedRole: 'delivery_partner',
      );
      final auth = StateNotifierProvider<SessionController, SessionState>(
        (ref) => session,
      );
      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp(
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(context)
                  .copyWith(textScaler: const TextScaler.linear(2)),
              child: child!,
            ),
            home: loginForm(auth),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('Sign in'),
        250,
        scrollable: find.byType(Scrollable).first,
      );
      expect(tester.takeException(), isNull);
      expect(find.byType(Scrollable), findsWidgets);
    },
  );
}
