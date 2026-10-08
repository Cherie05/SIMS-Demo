# 0010 Self-hosted observability

**Decision.** JSON logs on stdout with request id, user id, service, environment and secret
redaction; Prometheus metrics (request rate, errors and latency by route template, plus business,
security, job and browser metrics) on the API and the worker; alert rules tied to the SLOs and the
runbook; a Grafana dashboard provisioned as code; browsers report JavaScript errors and Core Web
Vitals to the API. One request id travels from the edge through nginx, the API, the audit trail and
any background job the request created.

**Consequences.** No third-party processor sees user data. Logs ship to Loki/ELK/CloudWatch with the
platform's collector; OpenTelemetry tracing can be added in the middleware without changing the
correlation already in place.
