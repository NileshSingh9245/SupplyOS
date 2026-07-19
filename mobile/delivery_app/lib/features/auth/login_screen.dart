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
  bool _busy = false; String? _err;

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
              const SizedBox(height: 40),
              Text('SUPPLYOS · DELIVERY', style: t.labelSmall),
              const SizedBox(height: 8),
              Text('Ready to roll.', style: t.displayLarge),
              const SizedBox(height: 32),
              TextField(controller: _email, decoration: const InputDecoration(labelText: 'Email'),
                keyboardType: TextInputType.emailAddress),
              const SizedBox(height: 12),
              TextField(controller: _pw, obscureText: true, decoration: const InputDecoration(labelText: 'Password')),
              if (_err != null) Padding(padding: const EdgeInsets.only(top: 12),
                child: Text(_err!, style: const TextStyle(color: Colors.redAccent))),
              const Spacer(),
              SizedBox(width: double.infinity, child: ElevatedButton(
                onPressed: _busy ? null : () async {
                  setState(() { _busy = true; _err = null; });
                  try { await ref.read(authProvider.notifier).login(_email.text, _pw.text); }
                  catch (e) { setState(() => _err = e.toString()); }
                  finally { if (mounted) setState(() => _busy = false); }
                },
                child: Text(_busy ? 'Signing in…' : 'Sign in →'),
              )),
            ],
          ),
        ),
      ),
    );
  }
}
