# 0005 Second factor on every sign-in

**Context.** Passwords get phished and reused. The product owner asked for one-time codes that
appear in the server log for the demo.

**Decision.** Every sign-in needs a second step: a 6-digit code (5-minute validity, 5 attempts,
stored as an HMAC, delivered to the log or by email) or, once enrolled, an authenticator app (TOTP,
RFC 6238; secret encrypted with Fernet; a code can't be replayed within its window) with 10
single-use recovery codes. Password reset uses the same code mechanism and never reveals whether an
account exists. Passwords are hashed with Argon2id; old bcrypt hashes are upgraded at sign-in.

**Consequences.** `OTP_DELIVERY=log` is for demos; production uses `email` or authenticator apps and
the server warns at start-up otherwise. SSO (OIDC/SAML) would replace the password and code steps
for organisations with an identity provider; the session model stays the same.
