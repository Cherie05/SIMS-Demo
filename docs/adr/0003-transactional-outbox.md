# 0003 Transactional outbox + worker instead of a message broker

**Context.** Emails must go out after an order is created or decided, must never be sent for a
change that rolled back, must survive the API crashing right after commit, and must not slow down
or fail the request when SMTP is slow or down.

**Decision.** Jobs are rows in `outbox_jobs`, written in the same transaction as the business change.
Worker processes claim due jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, retry with exponential
backoff and jitter (15 s up to 1 h), and move a job to DEAD (dead-letter) after 6 failures, or at
once on a permanent SMTP rejection. Jobs of a crashed worker are reclaimed when their lock expires.
Admins see and retry dead jobs on the System page. Sign-in codes are encrypted while queued and
wiped after sending; jobs past their deadline expire instead of arriving late.

**Consequences.** No broker (RabbitMQ/Kafka/Celery) to run and secure, and exactly-once
*enqueueing*. Delivery is at-least-once, so handlers are written to be safe to repeat. If volume
ever needs a broker, a relay can publish outbox rows to it without changing the producers.
