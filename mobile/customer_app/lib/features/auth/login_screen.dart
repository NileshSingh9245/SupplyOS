import 'package:flutter/material.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'auth_provider.dart';

class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});
  @override
  Widget build(BuildContext context) => SessionLoginForm(
        sessionProvider: authProvider,
        label: 'SUPPLYOS / CUSTOMER',
        title: 'Your supply, in view.',
        description: 'Sign in to view the catalog and your orders.',
      );
}
