# SupplyOS Test Credentials

## Super Admin (created via /api/v1/setup/initialize during this session)
- Email: `admin@acme.com`
- Password: `AdminPass123!`
- Role: `super_admin`
- Tenant: `Acme Wholesale Pvt Ltd` (currency INR)

## Auth endpoints
- Login: `POST /api/v1/auth/login`  body `{"email":"admin@acme.com","password":"AdminPass123!"}`
- Me: `GET /api/v1/auth/me`
- Register customer: `POST /api/v1/auth/register-customer`
- Refresh: `POST /api/v1/auth/refresh`
- Logout: `POST /api/v1/auth/logout`
- Forgot password: `POST /api/v1/auth/forgot-password`
- Reset password: `POST /api/v1/auth/reset-password`

## Setup
- Status: `GET /api/v1/setup/status`
- Initialize: `POST /api/v1/setup/initialize` (only if not yet initialized)

## Notes
- JWT + refresh in httpOnly cookies, cookie name `access_token`, `refresh_token`.
- Bearer header fallback on `Authorization: Bearer <token>`.
- Backend base: `https://3e295af5-2bfc-4745-b3a3-3b12451cf1df.preview.emergentagent.com`
- Local backend: `http://localhost:8001`
