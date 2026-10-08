# Service levels, recovery objectives and alerting

## Proposed SLIs and SLOs (rolling 30 days)

These are production targets, not claims of achieved service levels. The local load run in
[performance.md](performance.md) verifies a short workload against latency and error thresholds;
it does not establish 30-day compliance. Assign a service owner, define the production SLIs and
retain at least 30 days of telemetry. The bundled Prometheus configuration retains 15 days by
default, so a 30-day evaluation needs longer retention or an external metrics store.

| SLI | Measured from | SLO | Alert |
|---|---|---|---|
| Availability: share of API requests that don't fail with 5xx | `sims_http_requests_total` | ≥ 99.9 % of requests | `HighErrorRate` (> 1 % for 5 min), `ApiDown` |
| Latency: p95 of API requests | `sims_http_request_duration_seconds` | < 500 ms (p50 < 200 ms, p99 < 1 s) | `HighLatencyP95` (10 min) |
| Email freshness: notifications delivered | Define delivery-latency SLI; use outbox backlog and dead-letter count as supporting indicators | 99 % within 5 minutes; no job dead-lettered unseen | `JobsBacklogGrowing`, `JobsDeadLettered`, `WorkerNotRunning` |
| Page experience: Largest Contentful Paint p75 | browser telemetry (`sims_web_vitals`) | < 2.5 s | `SlowPageLoads` |

**Proposed error budget policy.** When more than half the 30-day error budget is spent, pause
feature releases and prioritize the reliability issue identified by incident reviews. The service
owner must review the budget before release; this policy is not an automated deployment gate.

## Recovery targets and required preparation

RPO is the target maximum loss of committed data; RTO is the target time to restore service.
Validate both through timed recovery exercises on the actual production platform. Restart policies,
backup scripts and local QA checks do not guarantee these recovery times.

| Scenario | RPO target | RTO target | Required preparation |
|---|---|---|---|
| Container or process crash | 0 committed records | < 1 min | durable database storage, restart policies, readiness checks and measured restart time |
| Host loss (Compose deployment) | ≤ 24 h | ≤ 2 h | successful daily backups copied off-site, retained encryption keys, replacement-host provisioning and a tested restore procedure |
| Bad release | 0 | < 10 min | recorded previous release and demonstrated compatibility with the current database schema; otherwise prepare a forward fix |
| Data corruption / accidental deletion | recover to the minute before the event | ≤ 4 h | validated backup recovery, retained binlogs and a tested point-in-time replay procedure |
| Managed-cloud deployment target | ≤ 5 min | ≤ 30 min | provision and validate managed HA/PITR; this infrastructure is not included in the Compose deployment |

The production backup loop is configured to restore each new backup into a scratch database and
check table count, audit triggers and migration version. Inspect `restore-check-latest.json` in the
backup directory and the backup container's health check. This verifies a local restore path;
operators must configure and verify off-site copying and binlog archival separately.

Image rollback does not downgrade the database and may fail readiness when an older image does
not recognize a newer schema. Expand-only migration design alone does not prove rollback
compatibility. Test the intended rollback image against the migrated schema before release, and
use a forward fix when compatibility cannot be demonstrated.

Require a full restore drill on a separate host at least quarterly. Record the backup used, elapsed
recovery time, observed data loss, application checks, operator and follow-up actions in the
[runbook drill log](runbook.md#restore-drill-log). This document sets the drill requirement; it does
not report completed quarterly drills.

## Required on-call and escalation process

Before production use, assign primary and backup responders, define coverage hours and escalation
contacts, and assign incident-command responsibility. Agree on and test the following response
targets with the operating team:

| Severity | Examples | Response target |
|---|---|---|
| SEV1 | API down, data loss, security breach | page on-call immediately, incident commander, status update every 30 min |
| SEV2 | SLO burning fast, emails not sent, sign-in broken for some users | page during business hours, fix or mitigate same day |
| SEV3 | single alert with workaround, dead-lettered email | ticket, next business day |

The repository supplies Prometheus alert rules and Grafana dashboards. Pager and team-channel
delivery are not provisioned by the Compose stack. Operators must configure Alertmanager or the
platform's equivalent, then test receivers and escalation using the `severity` label: `critical`
to the pager, `warning` to the team channel, and `info` to the dashboard. Record a successful test
of notification delivery before relying on alerts for incident response.
