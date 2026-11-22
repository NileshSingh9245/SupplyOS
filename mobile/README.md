# SupplyOS Flutter Mobile Apps

Two presentation-only Flutter applications sharing a server-authoritative backend. Signed review APKs exist; the applications are not complete production workflows.

- **customer_app/**: customer-effective catalog and read-only paginated order/detail/history views. Cart/checkout, tracking, invoices and credit/payment views remain incomplete.
- **delivery_app/**: exact delivery-partner authentication and read-only assigned routes. QR/OTP, proof/collection, maps and offline synchronization remain incomplete.

## Shared packages
Both apps consume `packages/supplyos_core/` which contains:
- `api_client.dart` — Dio-based HTTP client with cookie/JWT handling, refresh interceptor
- Typed role-specific JSON/decimal/date/pagination contracts; these are not generated OpenAPI capabilities.
- Memory-only Riverpod session/cookies, bounded refresh and account/query generation barriers.
- `theme.dart` — light theme (customer app) + dark theme (delivery app) mirroring the design system
- `formatters.dart` — INR / date formatters (matches `frontend/src/lib/utils.ts`)

## Architecture doctrine
Flutter apps are **presentation only**. All business logic lives in the FastAPI backend. Do not compute pricing, credit, or inventory states client-side.

State management: **Riverpod**. Navigation: **go_router**. Sessions are online/memory-only; no Hive outbox or encrypted offline persistence is implemented.

## Running locally
```bash
# 1. Use the approved Flutter >=3.47 / Dart >=3.13 toolchain.
flutter --version

# 2. Configure SUPPLYOS_API_BASE for the backend you operate.
cd customer_app && flutter run
cd delivery_app && flutter run
```

## Environment
Both apps read `SUPPLYOS_API_BASE` from `--dart-define`:
```bash
flutter run --dart-define=SUPPLYOS_API_BASE=https://api.your-domain.example/api/v1
```

## Signed Review Checkpoint - 2026-11-15 UTC

- Verified API origin: `https://supplyos-client-review-api.onrender.com`; compile-time API is that origin plus `/api/v1`. It is supplied explicitly, not a new source fallback.
- Both `0.1.0-review` releases are built and installed on isolated `emulator-5580`, API35, using ADB5038. Packages are `com.supplyos.customer.review` and `com.supplyos.delivery.review`, with visible Review launcher labels, no debug/JNI-debug release flags, backup/cleartext disabled and Internet-only permission.
- APKs include `armeabi-v7a`, `arm64-v8a` and `x86_64`, minSDK24/targetSDK36. Separate RSA3072 keys were independently checked by `apksigner`; protected PKCS12/DPAPI credentials remain private and production releases remain unsigned/held.
- Customer APK: `customer_app/build/app/outputs/flutter-apk/app-review-release.apk`; SHA256 `f3637e64a23400e53b2c2dacdb2180afefd49f7821813a17e1e337070ecb1173`.
- Delivery APK: `delivery_app/build/app/outputs/flutter-apk/app-review-release.apk`; SHA256 `ea9e94be4a4d46ad30bc6e9ccdfa0f550ba95d092cf833733f1d260518986e06`.
- Native nonexistent-account attempts reached the hosted HTTPS API, returned401 with safe messages and cleared password fields. Both login screens render, and application-scoped crash buffers were clear. Emulator Bluetooth boot errors are system issues, not a claim that its entire crash buffer is empty.
- Owner setup and authenticated cross-role acceptance remain pending; no client passwords/demo accounts were generated. The free review database expires2026-12-14, services cold-start, cache persistence is off and proof files are ephemeral. Synthetic review only, not production durability or complete feature acceptance.
- Local baseline remains263 VM passes and three clean analyses; the later native smoke is separate evidence. The current Kotlin plugin compiles successfully but Flutter warns a future toolchain requires built-in Kotlin migration. An unused Cupertino font-family warning appeared in the customer build; visible Material UI rendered correctly.

Rebuild only after independently verifying the public API and using the original signing-owner Windows account:

```powershell
& ".\mobile\review-android.ps1" -Action Build -App both -VerifiedApiOrigin "https://supplyos-client-review-api.onrender.com"
```

The helper restores process environment, keeps caches/temp/NDK on ignored D: runtime, bounds Gradle to3GiB/two workers and refuses Java/Android auto-download. Do not reinitialize existing signing or accept blanket licenses. Generated APKs/screenshots/private files are excluded from source publication. Release guard checks remain available with `-Action VerifyGuards`; they do not build final APKs.

## Backend Connections
There is no development or release API fallback. Supply `SUPPLYOS_API_BASE` explicitly. Release/profile requires a reviewed public HTTPS `/api/v1`; debug accepts explicit diagnostic loopback/emulator origins. The current review artifacts use the verified hosted API and do not depend on developer-PC services. Platform/browser and authenticated acceptance are separate from VM tests.
