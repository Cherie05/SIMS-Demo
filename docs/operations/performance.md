# Performance and capacity

## Load test (k6)

Script: [`loadtest/k6/api-load.js`](../../loadtest/k6/api-load.js). The tested traffic mix ramps to
30 browsing virtual users (dashboard summary, sales trend, top products, product search, order and
customer lists, with think time), alongside 2 order creations per second using idempotency keys.
The preparation script creates 20 distinct users. Thresholds are p95 < 500 ms, p99 < 1 s,
server errors < 0.1 %, successful checks > 99.9 %, and order creation p95 < 800 ms.

```bash
cd e2e && python ../loadtest/prepare.py --users 20        # users, customer, product; tokens for 15 minutes
docker run --rm --network sims_app -v "$PWD/../loadtest:/loadtest" -w /loadtest/k6 grafana/k6:2.3.0 \
    run -e BASE_URL=http://backend:8000 api-load.js
```

The capacity run targets the API service directly, bypassing nginx. Only in this isolated QA
environment, `API_RATE_LIMIT_PER_IP_PER_MINUTE=0` avoids treating all virtual users as one client
because they share the load generator's IP. Per-user limits remain enabled. Retain production
limits and test the public proxy path separately.

## Measured results (2026-10-07, local Docker Desktop)

| Setup | Requests | Throughput | p50 | p95 | p99 | HTTP failures / 5xx | Thresholds |
|---|---|---|---|---|---|---|---|
| 2 API replicas, each limited to 1 CPU / 512 MB | 10,177 | 59.206 req/s | 18.017 ms | 79.884 ms | 144.691 ms | 0 % / 0 % | All passed |

Source: [`load-api-capacity.json`](../qa/load-api-capacity.json). All 10,177 response checks passed,
including 301 order creations. Order creation p95 was **200.553 ms**, below its 800 ms threshold.

These measurements describe this workload and machine. They do not establish a per-CPU capacity
rule, spare production headroom, or performance after losing a replica. Size the intended workload
empirically, including realistic data volumes, public proxy traffic and failure scenarios.

The initial nginx-path run hit its **30 requests/s shared-IP limit**: **52.4 %** of requests received
429 responses, with no 5xx responses. Its response checks, p99 latency and order-latency thresholds
failed, as recorded in [`load-proxy-limits.json`](../qa/load-proxy-limits.json). This is evidence of
rate-limit enforcement and a failed workload run, not a capacity pass. Nginx keeps this limit for
production; the direct API run isolates application capacity from that shared-IP constraint.

## Frontend budget

`npm run size` checks gzip-compressed sizes in KiB (1,024 bytes), although its console labels them
KB. Current measurements and CI limits are:

| JavaScript measurement | Current | Limit |
|---|---|---|
| Entry | 32.0 KiB | 80 KiB |
| Largest chunk | Approximately 114.0 KiB | 160 KiB |
| Total | 418.9 KiB | 520 KiB |

Pages are lazy-loaded; charts and MUI are separate cacheable chunks. Hashed assets have a one-year
immutable cache policy.

## Database

Review indexes and query plans against the intended workload as data grows. The slow-query log
records statements taking more than 1 s. API database sessions set a 15 s SELECT execution limit
and a 10 s row-lock wait limit by default.
