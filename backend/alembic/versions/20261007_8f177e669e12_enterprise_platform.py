"""enterprise platform: audit trail, sessions, MFA, outbox, idempotency

- audit_logs (append-only, enforced by triggers)
- user_sessions (+ refresh_tokens.session_id): session listing, revocation, idle/absolute timeouts
- users: authenticator app (TOTP) columns, password_changed_at, last_login_at; mfa_recovery_codes
- otp_challenges: method column, PASSWORD_RESET purpose
- outbox_jobs, worker_heartbeats, scheduled_task_runs: background worker
- idempotency_keys

Expand-only for existing tables (new nullable columns, new tables), so the previous release keeps
working against the upgraded schema during a rolling deploy.

Creating triggers needs the server option log_bin_trust_function_creators=ON (set in
docker-compose; on managed MySQL, set it in the parameter group).

Revision ID: 8f177e669e12
Revises: 3e70d5c9b979
Create Date: 2026-10-07 13:59:57.016934
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "8f177e669e12"
down_revision: str | None = "3e70d5c9b979"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of app.models.audit.AUDIT_TRIGGERS at the time of this migration.
AUDIT_TRIGGERS = [
    """
    CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'
    """,
    """
    CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs FOR EACH ROW
    BEGIN
        IF OLD.occurred_at > UTC_TIMESTAMP() - INTERVAL 400 DAY THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs rows can only be deleted after the retention period';
        END IF;
    END
    """,
]
DROP_AUDIT_TRIGGERS = ["DROP TRIGGER IF EXISTS audit_logs_no_update", "DROP TRIGGER IF EXISTS audit_logs_no_delete"]

NEW_TABLES = [
    "outbox_jobs",
    "user_sessions",
    "mfa_recovery_codes",
    "idempotency_keys",
    "audit_logs",
    "worker_heartbeats",
    "scheduled_task_runs",
]


def upgrade() -> None:
    op.create_table(
        "scheduled_task_runs",
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("last_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=10), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_result", sa.JSON(), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_scheduled_task_runs")),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=80), nullable=False),
        sa.Column("hostname", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("jobs_processed", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_worker_heartbeats")),
    )
    op.create_index(op.f("ix_worker_heartbeats_last_seen_at"), "worker_heartbeats", ["last_seen_at"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", mysql.DATETIME(fsp=3), server_default=sa.text("now(3)"), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("actor_role", sa.String(length=20), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_logs_actor_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_action_occurred", "audit_logs", ["action", "occurred_at"], unique=False)
    op.create_index("ix_audit_logs_actor_occurred", "audit_logs", ["actor_id", "occurred_at"], unique=False)
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"], unique=False)
    for statement in AUDIT_TRIGGERS:
        op.execute(statement)

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("idem_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_idempotency_keys_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("user_id", "scope", "idem_key", name="uq_idempotency_keys_user_scope_key"),
    )
    op.create_index(op.f("ix_idempotency_keys_expires_at"), "idempotency_keys", ["expires_at"], unique=False)

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_mfa_recovery_codes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mfa_recovery_codes")),
    )
    op.create_index(op.f("ix_mfa_recovery_codes_user_id"), "mfa_recovery_codes", ["user_id"], unique=False)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_reason", sa.String(length=20), nullable=True),
        sa.Column("mfa_method", sa.String(length=20), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
    )
    op.create_index("ix_user_sessions_user_revoked", "user_sessions", ["user_id", "revoked_at"], unique=False)

    op.create_table(
        "outbox_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.String(length=80), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=150), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_outbox_jobs_created_by_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["sales_orders.id"], name=op.f("fk_outbox_jobs_order_id_sales_orders"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_jobs")),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_jobs_dedupe_key"),
    )
    op.create_index("ix_outbox_jobs_due", "outbox_jobs", ["status", "available_at", "priority"], unique=False)
    op.create_index(op.f("ix_outbox_jobs_order_id"), "outbox_jobs", ["order_id"], unique=False)

    op.add_column("otp_challenges", sa.Column("method", sa.String(length=10), server_default="code", nullable=False))
    op.alter_column(
        "otp_challenges",
        "purpose",
        existing_type=mysql.ENUM("SIGNUP", "LOGIN", collation="utf8mb4_unicode_ci"),
        type_=sa.Enum("SIGNUP", "LOGIN", "PASSWORD_RESET", name="otp_purpose"),
        existing_nullable=False,
    )

    op.add_column("refresh_tokens", sa.Column("session_id", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_refresh_tokens_session_id"), "refresh_tokens", ["session_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_refresh_tokens_session_id_user_sessions"),
        "refresh_tokens",
        "user_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Tokens from before sessions existed can't be tied to a session: those users simply sign in again.
    op.execute(
        "UPDATE refresh_tokens SET revoked_at = UTC_TIMESTAMP(), revoked_reason = 'upgrade' "
        "WHERE session_id IS NULL AND revoked_at IS NULL"
    )

    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("totp_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("totp_last_used_step", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("totp_pending_secret_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in (
        "totp_pending_secret_encrypted",
        "totp_last_used_step",
        "totp_enabled_at",
        "totp_secret_encrypted",
        "last_login_at",
        "password_changed_at",
    ):
        op.drop_column("users", column)

    op.drop_constraint(op.f("fk_refresh_tokens_session_id_user_sessions"), "refresh_tokens", type_="foreignkey")
    op.drop_index(op.f("ix_refresh_tokens_session_id"), table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "session_id")

    # The old enum has no PASSWORD_RESET: those short-lived challenges are dropped first.
    op.execute("DELETE FROM otp_challenges WHERE purpose = 'PASSWORD_RESET'")
    op.alter_column(
        "otp_challenges",
        "purpose",
        existing_type=sa.Enum("SIGNUP", "LOGIN", "PASSWORD_RESET", name="otp_purpose"),
        type_=mysql.ENUM("SIGNUP", "LOGIN", collation="utf8mb4_unicode_ci"),
        existing_nullable=False,
    )
    op.drop_column("otp_challenges", "method")

    for statement in DROP_AUDIT_TRIGGERS:
        op.execute(statement)
    # Dropping a table drops its indexes and foreign keys too.
    for table in NEW_TABLES:
        op.drop_table(table)
