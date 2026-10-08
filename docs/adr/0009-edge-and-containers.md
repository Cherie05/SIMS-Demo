# 0009 Caddy TLS edge, hardened containers, least-privilege database accounts

**Decision.**
- Caddy terminates TLS with automatic certificates, redirects HTTP to HTTPS, adds HSTS and a
  request id. nginx (unprivileged) serves the SPA with a strict same-origin CSP and proxies `/api`,
  trusting X-Forwarded-For only from the edge's fixed address.
- Every container: pinned image, non-root where the image allows, read-only root filesystem, all
  Linux capabilities dropped (MySQL keeps the five its entrypoint needs, the edge only
  NET_BIND_SERVICE), no-new-privileges, CPU/memory/PID limits, rotated logs, health checks.
- Networks: `app` and `data` are internal in production; only the edge (certificates) and the
  worker (SMTP) can reach the internet.
- MySQL accounts: owner (migrations), `sims_app` (data only, no DDL), `sims_backup` (read-only),
  `sims_restore` (scratch database only); TLS required for every connection.

**Consequences.** A compromised API container can't change the schema, can't reach the internet and
can't write to its own filesystem. For public internet exposure a managed WAF/CDN in front of the
edge is recommended (see the readiness matrix).
