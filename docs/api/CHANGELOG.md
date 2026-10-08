# API changelog (`/api/v1`)

## 1.1.0 - 2026-10-07 (additive)

- **Auth**: `POST /auth/password/forgot`, `POST /auth/password/reset`, `POST /auth/password/change`;
  `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/sessions/revoke-all`;
  `GET /auth/mfa`, `POST /auth/mfa/totp/setup|enable|disable`, `POST /auth/mfa/recovery-codes`.
  `POST /auth/otp/verify` accepts `recovery_code` instead of `code`. Challenges include `method`
  (`code`/`totp`); `delivery` may be `authenticator`; `destination` may be null.
- **Sessions**: `SessionOut` adds `session_id` and `session_expires_in`; `user` adds `permissions`,
  `totp_enabled`, `last_login_at`, `password_changed_at`. Access tokens are rejected once their
  session ends (`SESSION_REVOKED`).
- **Users**: `POST /users/{id}/sessions/revoke`, `POST /users/{id}/mfa/reset`.
- **Orders**: `Idempotency-Key` on `POST /orders` and stock adjustments. Orders a user may not see
  now return 404 instead of 403. `emails[].status` may be `QUEUED` (waiting for the worker).
- **Operations**: `GET /audit-logs`, `GET /audit-logs/export`, `GET /system/status`, `GET /system/jobs`,
  `POST /system/jobs/{id}/retry`, `GET /feature-flags`, `PUT /feature-flags/{name}`.
- **Telemetry**: `POST /telemetry/client-errors`, `POST /telemetry/web-vitals`.
- **Platform**: every response has `X-Request-ID`; errors include `request_id`; new error codes
  `RATE_LIMITED`, `PAYLOAD_TOO_LARGE`, `UNSUPPORTED_MEDIA_TYPE`, `FEATURE_DISABLED`,
  `IDEMPOTENCY_KEY_INVALID`, `IDEMPOTENCY_KEY_REUSED`, `PASSWORD_POLICY`, `PASSWORD_INCORRECT`,
  `PASSWORD_REUSED`, `RESET_CODE_INVALID`, `LAST_ADMIN`, `SESSION_REVOKED`. Request bodies must be
  `application/json`.
- Health: `/health/live`, `/health/ready` (outside `/api/v1`), `/metrics` (internal port only).

## 1.0.0 - 2026-10-06

Initial release: auth with one-time codes, users, customers, products, inventory ledger, orders with
manager approval, dashboard, settings.
