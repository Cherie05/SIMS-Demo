# Architecture decision records

Short records of decisions that shape the system: the context, the choice, and what it costs.
New decisions get the next number; a reversed decision is marked *Superseded* rather than deleted.

| # | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith, not microservices | Accepted |
| [0002](0002-mysql-system-of-record.md) | MySQL 8.4 as the system of record | Accepted |
| [0003](0003-transactional-outbox.md) | Transactional outbox + worker instead of a message broker | Accepted |
| [0004](0004-sessions-and-tokens.md) | In-memory access token + rotating httpOnly refresh cookie + server-side sessions | Accepted |
| [0005](0005-second-factor.md) | Second factor on every sign-in: one-time code or authenticator app | Accepted |
| [0006](0006-permissions.md) | Permissions on top of roles; deny by default | Accepted |
| [0007](0007-append-only-audit.md) | Append-only audit trail enforced by the database | Accepted |
| [0008](0008-valkey-for-shared-limits.md) | Valkey for shared rate limits, with graceful fallback | Accepted |
| [0009](0009-edge-and-containers.md) | Caddy TLS edge, hardened containers, least-privilege DB accounts | Accepted |
| [0010](0010-observability-without-vendors.md) | Self-hosted observability: JSON logs, Prometheus, browser telemetry | Accepted |
