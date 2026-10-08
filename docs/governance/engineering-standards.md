# Engineering standards

## Repository rules (GitHub settings for `main`)

- Pull requests required. This public assignment repository has one maintainer, so required
  approvals are set to 0; the owner cannot approve their own pull requests. All CI checks and
  conversation resolution remain required, with no bypass actors. `CODEOWNERS` routes review
  requests to `@Cherie05` and grants no permissions.
- Required status checks use the exact job names listed in
  [Public repository setup](../github-repository-setup.md): deployment checks, backend, frontend,
  security scans, both container images, end-to-end acceptance/DAST and all three CodeQL jobs.
  Branch must be up to date; linear history (squash merge).
- No force pushes or deletions; signed commits recommended; secret scanning and push protection on.
- Dependabot security updates on; version updates weekly with a 7-day cooldown.
- When another trusted maintainer joins, require at least 1 approval and code-owner review.
  For a larger security team, consider 2 approvals for sensitive changes. Do not enable these
  review requirements while the owner is the only person who can review.

## Definition of done

- Tests for the change (unit/integration; acceptance step if user-facing), all gates green:
  ruff, mypy, pytest (≥ 90 % coverage), ESLint, TypeScript strict, Prettier, Vitest, bundle budget,
  pip-audit, npm audit, bandit, Semgrep, Gitleaks, Trivy, migration round trip, API contract.
- New endpoint: declares a permission, audits security-relevant actions, has a refusal test.
- New setting: in `config.py` with a safe default, in `.env.example`, validated for production if it
  matters for security.
- Operations: new failure modes have a metric, an alert if user-facing, and a runbook entry.
- Accessibility: new pages pass axe (WCAG 2.1 AA) and work at 390 px width.

## Release checklist

- [ ] CHANGELOG and `docs/api/CHANGELOG.md` updated; version bumped (`APP_VERSION`, `frontend/package.json`)
- [ ] Migrations are expand-only (or this is the planned contract step)
- [ ] Staging deployed from the same image digests; acceptance suite green against staging
- [ ] Release approved in the `production` environment (second person)
- [ ] Post-deploy smoke test green; dashboards normal for 30 minutes

## Launch checklist (first production go-live)

- [ ] Real domain, DNS (with DNSSEC/CAA where available), SPF/DKIM/DMARC for the mail domain
- [ ] `production.env` from the secret manager; `OTP_DELIVERY=email` or authenticator apps required
- [ ] Off-site backup copy configured; first full restore drill done and logged
- [ ] Monitoring overlay or platform equivalent; alerts routed to on-call
- [ ] WAF/CDN in front of the edge; external penetration test; access review of admin accounts
- [ ] Data-protection notice and retention settings agreed with the business
