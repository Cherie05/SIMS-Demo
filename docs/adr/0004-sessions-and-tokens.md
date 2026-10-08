# 0004 In-memory access token + rotating refresh cookie + server-side sessions

**Context.** Tokens in localStorage are readable by any injected script; long-lived JWTs can't be
revoked; sessions must end on sign-out, password change, deactivation and when idle.

**Decision.** A 15-minute JWT (HS256 with a key id for rotation; issuer, audience and type checked)
kept only in memory. A refresh token that is opaque, stored hashed, sent only in an httpOnly,
Secure, SameSite=Strict cookie scoped to `/api/v1/auth`, rotated on every use, with reuse
detection. Each sign-in creates a `user_sessions` row (idle timeout through the refresh expiry,
12-hour absolute lifetime) and the access token carries its id, which every request checks - so
revocation takes effect immediately.

**Consequences.** One extra primary-key lookup per request. Users see and end their sessions on the
Account page; admins can sign a user out everywhere. CSRF is covered by SameSite=Strict plus a
required custom header on the cookie endpoints, and by refusing non-JSON request bodies.
