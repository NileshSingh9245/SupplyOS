import 'package:flutter_test/flutter_test.dart';

Future<void> pumpUntil(WidgetTester tester, bool Function() ready) async {
  for (var frame = 0; frame < 40; frame++) {
    if (ready()) return;
    await tester.pump(const Duration(milliseconds: 20));
  }
  fail('Offline fixture did not settle within the bounded frame budget.');
}
