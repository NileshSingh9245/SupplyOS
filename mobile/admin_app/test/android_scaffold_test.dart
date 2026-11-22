import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'new Admin runner is separate and applies existing reviewed signing guard',
    () {
      final build = File('android/app/build.gradle.kts').readAsStringSync();
      expect(build, contains('applicationId = "com.supplyos.admin"'));
      expect(build, contains('signingConfig = null'));
      expect(build, contains('review-signing.gradle'));
      expect(build, isNot(contains('signingConfigs.getByName("debug")')));
    },
  );
  test('private native screen and transport use no unnecessary plugin permissions/backups', () {
    final manifest = File('android/app/src/main/AndroidManifest.xml')
        .readAsStringSync();
    expect(manifest, contains('android:allowBackup="false"'));
    expect(manifest, contains('android:usesCleartextTraffic="false"'));
    expect(manifest, contains('android:windowSoftInputMode="adjustResize"'));
    expect(manifest, contains('android.permission.INTERNET'));
    expect(manifest, isNot(contains('android.permission.CAMERA')));
    expect(manifest, isNot(contains('READ_EXTERNAL_STORAGE')));
    final activity = File(
      'android/app/src/main/kotlin/com/supplyos/admin/MainActivity.kt',
    ).readAsStringSync();
    expect(activity, contains('FLAG_SECURE'));
  });
  test('application source is native and has no default API URL or private credentials', () {
    final source = File('lib/main.dart').readAsStringSync();
    final pubspec = File('pubspec.yaml').readAsStringSync();
    expect(source, isNot(contains('https://')));
    expect(source, isNot(contains('WebView')));
    expect(pubspec, isNot(contains('webview')));
    expect(pubspec, contains('go_router: 14.8.1'));
    expect(pubspec, contains('flutter_riverpod: 2.6.1'));
  });
}
