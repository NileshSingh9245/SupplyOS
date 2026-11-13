import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'failure.dart';
import 'session.dart';

class SessionRouterRefresh extends ChangeNotifier {
  void refresh() => notifyListeners();
}

class SessionLogoutButton extends ConsumerWidget {
  const SessionLogoutButton({required this.sessionProvider, super.key});

  final SessionProvider sessionProvider;

  @override
  Widget build(BuildContext context, WidgetRef ref) => IconButton(
    tooltip: 'Sign out',
    icon: const Icon(Icons.logout),
    onPressed: () => unawaited(ref.read(sessionProvider.notifier).logout()),
  );
}

class SessionLoginForm extends ConsumerStatefulWidget {
  const SessionLoginForm({
    required this.sessionProvider,
    required this.label,
    required this.title,
    required this.description,
    super.key,
  });

  final SessionProvider sessionProvider;
  final String label;
  final String title;
  final String description;

  @override
  ConsumerState<SessionLoginForm> createState() => _SessionLoginFormState();
}

class _SessionLoginFormState extends ConsumerState<SessionLoginForm> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _form = GlobalKey<FormState>();
  AppFailure? _failure;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (ref.read(widget.sessionProvider).isBusy ||
        !_form.currentState!.validate()) {
      return;
    }
    setState(() => _failure = null);
    try {
      await ref
          .read(widget.sessionProvider.notifier)
          .login(_email.text, _password.text);
    } catch (error) {
      if (mounted && AppFailure.safe(error).kind != FailureKind.superseded) {
        setState(() => _failure = AppFailure.safe(error));
      }
    } finally {
      if (mounted) _password.clear();
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(widget.sessionProvider);
    final unavailable = session.phase == SessionPhase.unavailable;
    final theme = Theme.of(context);
    final failure = _failure ?? session.failure;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                const SizedBox(height: 24),
                Text(widget.label, style: theme.textTheme.labelSmall),
                const SizedBox(height: 12),
                Text(widget.title, style: theme.textTheme.displayLarge),
                const SizedBox(height: 12),
                Text(widget.description, style: theme.textTheme.bodyLarge),
                const SizedBox(height: 32),
                Form(
                  key: _form,
                  child: Column(
                    children: [
                      TextFormField(
                        controller: _email,
                        enabled: !session.isBusy && !unavailable,
                        keyboardType: TextInputType.emailAddress,
                        textInputAction: TextInputAction.next,
                        autocorrect: false,
                        decoration: const InputDecoration(labelText: 'Email'),
                        validator: (value) =>
                            value == null || value.trim().isEmpty
                            ? 'Enter your email.'
                            : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _password,
                        enabled: !session.isBusy && !unavailable,
                        obscureText: true,
                        autocorrect: false,
                        enableSuggestions: false,
                        textInputAction: TextInputAction.done,
                        decoration: const InputDecoration(
                          labelText: 'Password',
                        ),
                        validator: (value) => value == null || value.isEmpty
                            ? 'Enter your password.'
                            : null,
                        onFieldSubmitted: (_) => _submit(),
                      ),
                    ],
                  ),
                ),
                if (failure != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Semantics(
                      liveRegion: true,
                      child: Text(
                        failure.message,
                        style: TextStyle(color: theme.colorScheme.error),
                      ),
                    ),
                  ),
                if (session.isLogoutPending)
                  const Padding(
                    padding: EdgeInsets.only(top: 16),
                    child: Text(
                      'Signed out of this app. Contacting the server...',
                    ),
                  ),
                if (session.logoutOutcome != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Text(
                      session.logoutOutcome == LogoutOutcome.confirmed
                          ? 'Signed out of this app. Server logout confirmed.'
                          : 'Signed out of this app. Server logout could not be confirmed.',
                    ),
                  ),
                if (session.phase == SessionPhase.checkFailed)
                  TextButton(
                    onPressed: () => ref
                        .read(widget.sessionProvider.notifier)
                        .retryBootstrap(),
                    child: const Text('Retry session check'),
                  ),
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: session.isBusy || unavailable ? null : _submit,
                  child: Text(switch (session.phase) {
                    SessionPhase.checking => 'Checking session...',
                    SessionPhase.signingIn => 'Signing in...',
                    _ => 'Sign in',
                  }),
                ),
                const SizedBox(height: 16),
                const Text(
                  'Online session only. Signing out clears this app\'s local data.',
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class ReadFeedback extends StatelessWidget {
  const ReadFeedback({
    required this.title,
    this.message,
    this.onRetry,
    super.key,
  });

  final String title;
  final String? message;
  final Future<void> Function()? onRetry;

  @override
  Widget build(BuildContext context) => ListView(
    physics: const AlwaysScrollableScrollPhysics(),
    padding: const EdgeInsets.all(24),
    children: [
      const SizedBox(height: 48),
      Text(title, style: Theme.of(context).textTheme.titleLarge),
      if (message != null)
        Padding(
          padding: const EdgeInsets.only(top: 12),
          child: Semantics(liveRegion: true, child: Text(message!)),
        ),
      if (onRetry != null)
        Padding(
          padding: const EdgeInsets.only(top: 16),
          child: Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton(
              onPressed: onRetry,
              child: const Text('Retry'),
            ),
          ),
        ),
    ],
  );
}

class ReadLoading extends StatelessWidget {
  const ReadLoading({super.key});

  @override
  Widget build(BuildContext context) => Center(
    child: Semantics(
      label: 'Loading',
      child: const CircularProgressIndicator(),
    ),
  );
}

class PageControls extends StatelessWidget {
  const PageControls({
    required this.page,
    required this.total,
    required this.onPrevious,
    required this.onNext,
    super.key,
  });

  final int page;
  final int total;
  final VoidCallback? onPrevious;
  final VoidCallback? onNext;

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: [
          IconButton(
            tooltip: 'Previous page',
            onPressed: onPrevious,
            icon: const Icon(Icons.chevron_left),
          ),
          Expanded(
            child: Text(
              'Page $page | $total total',
              textAlign: TextAlign.center,
            ),
          ),
          IconButton(
            tooltip: 'Next page',
            onPressed: onNext,
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
    ),
  );
}
