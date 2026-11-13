# SupplyOS Flutter Mobile Apps

Two production-grade Flutter applications sharing a single backend:

- **customer_app/** — customer ordering (catalog, cart, orders, tracking, invoices, credit history)
- **delivery_app/** — delivery partner (route, QR scan, OTP, proof, offline sync, cash/UPI collect)

## Shared packages
Both apps consume `packages/supplyos_core/` which contains:
- `api_client.dart` — Dio-based HTTP client with cookie/JWT handling, refresh interceptor
- `models/` — Order, Customer, Product, Delivery, Alert generated from FastAPI OpenAPI
- `auth_provider.dart` — Riverpod StateNotifier for auth session
- `settings_provider.dart` — cached tenant settings (currency, GST defaults)
- `theme.dart` — light theme (customer app) + dark theme (delivery app) mirroring the design system
- `formatters.dart` — INR / date formatters (matches `frontend/src/lib/utils.ts`)

## Architecture doctrine
Flutter apps are **presentation only**. All business logic lives in the FastAPI backend. Do not compute pricing, credit, or inventory states client-side.

State management: **Riverpod**. Navigation: **go_router**. Offline cache: **Hive** (delivery app only, for route data + queued proof uploads).

## Running locally
```bash
# 1. Install Flutter 3.16+
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

## Status (this milestone)
Skeleton generated with:
- pubspec.yaml + dependencies pinned
- Directory structure per feature
- Riverpod bootstrap + API client wiring
- Login screen + auth flow calling `/api/v1/auth/login`
- Routing scaffold

Screens for catalog / cart / route / OTP / proof are stubbed and will be filled in Milestone 3.

## Backend Connections
No cloud host or managed preview endpoint is hard-coded. The development fallback is `http://127.0.0.1:8001/api/v1`; a physical device must use your reachable LAN/HTTPS origin, and the standard Android emulator uses `10.0.2.2` to reach the host. Supply `SUPPLYOS_API_BASE` explicitly for your target. Flutter/platform tooling is still required and was not verified by the web preview.
