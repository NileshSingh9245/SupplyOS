import 'package:flutter/material.dart';
import 'package:supplyos_core/supplyos_core.dart';
import 'auth_provider.dart';

class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});
  @override
  Widget build(BuildContext context) => SessionLoginForm(
        sessionProvider: authProvider,
        label: 'SUPPLYOS / DELIVERY',
        title: 'Assigned to you.',
        description: 'View your current route. Online access only.',
      );
}
