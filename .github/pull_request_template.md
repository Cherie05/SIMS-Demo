## What and why

<!-- One or two sentences. Link the issue. -->

## How it was tested

- [ ] Unit / integration tests added or updated (`pytest`, `npm test`)
- [ ] Acceptance suite still passes (`e2e/`), if user-facing
- [ ] Tried it in the browser, including a phone-width screen, if UI

## Checklist

- [ ] No secrets, personal data or production data in code, tests, logs or screenshots
- [ ] Authorization: new endpoints declare a permission; tests cover the refusal path
- [ ] Database change? New Alembic migration that upgrades **and** downgrades; expand/contract if it touches live columns
- [ ] API change? `python -m scripts.export_openapi` run and `docs/api/CHANGELOG.md` updated (no breaking change in `/api/v1`)
- [ ] Security-relevant behaviour is audited (`audit_service.record`) and emits a metric if worth alerting on
- [ ] Docs / runbook updated if operations change (new setting, new alert, new failure mode)
