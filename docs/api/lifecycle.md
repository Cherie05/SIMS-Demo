# API lifecycle

- **Versioning**: every business endpoint lives under `/api/v1`. Within a major version changes are
  additive only (new endpoints, new optional fields, new enum values clients must tolerate).
- **Breaking changes** (removing or renaming a field/endpoint, tightening validation, changing
  semantics) go into `/api/v2`, served alongside v1.
- **Deprecation**: a deprecated v1 endpoint keeps working for at least 6 months, is marked
  `deprecated` in the OpenAPI document and answers with `Deprecation` and `Sunset` headers
  (RFC 9745 / RFC 8594) plus a `Link` to its replacement; usage is watched in the request metrics
  (`route` label) before removal.
- **Contract**: the OpenAPI document is generated from the code and committed at
  [`openapi.json`](openapi.json). CI fails if the API changes without regenerating it
  (`python -m scripts.export_openapi`), so every change is visible in review and recorded in the
  [changelog](CHANGELOG.md).
- **Errors** always use one envelope: `{"error": {"code", "message", "details", "request_id"}}`;
  `code` values are stable and documented in the changelog when added.
- **Idempotency**: `POST /orders` and `POST /products/{id}/stock-adjustments` accept an
  `Idempotency-Key`; retries with the same key return the original result
  (`Idempotent-Replayed: true`), keys are kept 24 hours.
- **Limits**: per-user and per-IP request budgets (429 with `Retry-After`), 1 MB bodies, JSON only,
  page size ≤ 100.
