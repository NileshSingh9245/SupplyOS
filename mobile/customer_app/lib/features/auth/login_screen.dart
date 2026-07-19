import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'auth_provider.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _pw = TextEditingController();
  bool _busy = false;
  String? _err;

  Future<void> _submit() async {
    setState(() { _busy = true; _err = null; });
    try {
      await ref.read(authProvider.notifier).login(_email.text, _pw.text);
      // router will redirect
    } catch (e) {
      setState(() => _err = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 24),
              Text('SUPPLYOS · CUSTOMER', style: t.labelSmall),
              const SizedBox(height: 8),
              Text('Order faster.', style: t.displayLarge),
              Text('Direct from the wholesaler.', style: t.titleLarge?.copyWith(color: Colors.black54)),
              const SizedBox(height: 40),
              TextField(controller: _email, keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Email')),
              const SizedBox(height: 12),
              TextField(controller: _pw, obscureText: true,
                decoration: const InputDecoration(labelText: 'Password')),
              if (_err != null) Padding(padding: const EdgeInsets.only(top: 12),
                child: Text(_err!, style: const TextStyle(color: Colors.red))),
              const Spacer(),
              SizedBox(width: double.infinity, child: ElevatedButton(
                onPressed: _busy ? null : _submit,
                child: Text(_busy ? 'Signing in…' : 'Sign in →'),
              )),
            ],
          ),
        ),
      ),
    );
  }
}
