# 0007 Append-only audit trail enforced by the database

**Context.** An audit log the application can edit proves little.

**Decision.** `audit_logs` records who (id, email and role snapshot), what (action, outcome), which
entity, old and new values, IP, user agent and request id - in the same transaction as the change,
or in its own transaction for refusals (failed sign-ins, denied access). MySQL triggers reject every
UPDATE, and any DELETE younger than the 400-day retention. Entries are also written as structured
log lines for a SIEM. Admins search and export them (CSV with spreadsheet-formula injection
neutralised; the export is itself audited).

**Consequences.** A compromised application account can't rewrite history; only a DBA dropping the
triggers could, which is itself visible. Retention runs as a scheduled job.
