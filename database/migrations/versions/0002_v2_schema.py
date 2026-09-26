"""v2: payment-rail boundary, risk audit trail, preferences, decimal money

Revision ID: 0002_v2_schema
Revises: 799ec06ed3d1
Create Date: 2026-09-26

* Money columns move from FLOAT to NUMERIC(14, 2).
* Timestamps become timezone-aware (existing naive values are treated as UTC).
* Payment attempts gain provider references, per-sender idempotency keys,
  exactly-once ledger flags and hashed simulated device/location signals.
* New tables: payment_state_transitions, provider_callback_events, user_preferences.

Written with batch operations so it runs on PostgreSQL (plain ALTERs) and on
SQLite (table rebuilds) alike.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_v2_schema"
down_revision: Union[str, Sequence[str], None] = "799ec06ed3d1"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)
MONEY = sa.Numeric(14, 2)

# table -> timestamp columns that become timezone-aware
TIMESTAMPS = {
    "app_configurations": ["updated_at"],
    "audit_events": ["created_at"],
    "demo_payment_accounts": ["created_at", "updated_at"],
    "feature_snapshots": ["created_at"],
    "model_metadata": ["training_date", "created_at"],
    "payment_attempts": ["created_at", "updated_at"],
    "recipients": ["created_at"],
    "risk_assessments": ["created_at"],
    "security_events": ["created_at"],
    "transaction_graph_edges": ["timestamp"],
    "users": ["created_at", "updated_at"],
}


def _tz(batch, table: str, column: str) -> None:
    using = f"{column} AT TIME ZONE 'UTC'" if op.get_bind().dialect.name == "postgresql" else None
    kw = {"postgresql_using": using} if using else {}
    batch.alter_column(column, existing_type=sa.DateTime(), type_=TZ, existing_nullable=False, **kw)


def upgrade() -> None:
    op.create_table(
        "provider_callback_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("event_id", sa.String(100), nullable=True),
        sa.Column("provider_reference", sa.String(80), nullable=True),
        sa.Column("reported_status", sa.String(20), nullable=True),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("detail", sa.String(255), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("received_at", TZ, nullable=False),
        sa.UniqueConstraint("provider", "event_id", name="uq_provider_callback_event"),
    )
    op.create_index("ix_provider_callback_events_provider_reference", "provider_callback_events",
                    ["provider_reference"])
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE",
                                                          name="fk_user_preferences_user"), nullable=False),
        sa.Column("hide_balance", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notify_on_high_risk", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("theme", sa.String(10), nullable=False, server_default="system"),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_user_preferences_user"),
    )
    op.create_table(
        "payment_state_transitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_attempt_id", sa.Integer(),
                  sa.ForeignKey("payment_attempts.id", ondelete="CASCADE", name="fk_transition_payment"),
                  nullable=False),
        sa.Column("from_state", sa.String(30), nullable=True),
        sa.Column("to_state", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("actor", sa.String(50), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_payment_state_transitions_payment_attempt_id", "payment_state_transitions",
                    ["payment_attempt_id"])

    for table in ("app_configurations", "audit_events", "model_metadata", "security_events"):
        with op.batch_alter_table(table) as b:
            for col in TIMESTAMPS[table]:
                _tz(b, table, col)
            if table == "model_metadata":
                b.add_column(sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()))
                b.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])

    with op.batch_alter_table("users") as b:
        for col in TIMESTAMPS["users"]:
            _tz(b, "users", col)
        b.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("is_fictional_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("last_login_at", TZ, nullable=True))
        b.drop_index("ix_users_phone_lookup_hash")
        b.create_index("ix_users_phone_lookup_hash", ["phone_lookup_hash"], unique=True)

    with op.batch_alter_table("demo_payment_accounts") as b:
        for col in TIMESTAMPS["demo_payment_accounts"]:
            _tz(b, "demo_payment_accounts", col)
        b.alter_column("simulated_balance", existing_type=sa.Float(), type_=MONEY, existing_nullable=False)
        b.add_column(sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.true()))
        b.create_check_constraint("ck_demo_account_balance_nonnegative", "simulated_balance >= 0")

    with op.batch_alter_table("recipients") as b:
        _tz(b, "recipients", "created_at")
        b.add_column(sa.Column("on_watchlist", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.drop_index("ix_recipients_upi_id_lookup_hash")
        b.create_index("ix_recipients_upi_id_lookup_hash", ["upi_id_lookup_hash"], unique=True)
    op.execute("UPDATE recipients SET on_watchlist = TRUE WHERE trust_level = 'suspicious'"
               if op.get_bind().dialect.name == "postgresql" else
               "UPDATE recipients SET on_watchlist = 1 WHERE trust_level = 'suspicious'")

    with op.batch_alter_table("payment_attempts") as b:
        for col in TIMESTAMPS["payment_attempts"]:
            _tz(b, "payment_attempts", col)
        b.alter_column("amount", existing_type=sa.Float(), type_=MONEY, existing_nullable=False)
        b.add_column(sa.Column("mode", sa.String(12), nullable=False, server_default="SIMULATION"))
        b.add_column(sa.Column("recipient_user_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("recipient_upi_enc", sa.Text(), nullable=True))
        b.add_column(sa.Column("recipient_name_enc", sa.Text(), nullable=True))
        b.add_column(sa.Column("note_enc", sa.Text(), nullable=True))
        b.add_column(sa.Column("decision", sa.String(20), nullable=True))
        b.add_column(sa.Column("provider_reference", sa.String(80), nullable=True))
        b.add_column(sa.Column("authorization_idempotency_key", sa.String(100), nullable=True))
        b.add_column(sa.Column("simulated_outcome", sa.String(10), nullable=True))
        b.add_column(sa.Column("verification_completed_at", TZ, nullable=True))
        b.add_column(sa.Column("balance_applied", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("balance_reversed", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("device_hash", sa.String(64), nullable=True))
        b.add_column(sa.Column("location_hash", sa.String(64), nullable=True))
        b.add_column(sa.Column("completed_at", TZ, nullable=True))
        b.drop_index("ix_payment_attempts_idempotency_key")
        b.create_index("ix_payment_attempts_idempotency_key", ["idempotency_key"], unique=False)
        b.create_index("ix_payment_attempts_provider_reference", ["provider_reference"], unique=True)
        b.create_index("ix_payment_attempts_recipient_user_id", ["recipient_user_id"])
        b.create_index("ix_payment_recipient_created", ["recipient_upi_lookup_hash", "created_at"])
        b.create_index("ix_payment_sender_created", ["sender_user_id", "created_at"])
        b.create_unique_constraint("uq_payment_sender_idempotency", ["sender_user_id", "idempotency_key"])
        b.create_unique_constraint("uq_payment_sender_auth_idempotency",
                                   ["sender_user_id", "authorization_idempotency_key"])
        b.create_foreign_key("fk_payment_recipient_user", "users", ["recipient_user_id"], ["id"])
        b.create_check_constraint("ck_payment_amount_positive", "amount > 0")
    # Completed v1 payments already debited their balance.
    op.execute("UPDATE payment_attempts SET balance_applied = (state = 'COMPLETED')")

    with op.batch_alter_table("risk_assessments") as b:
        _tz(b, "risk_assessments", "created_at")
        b.alter_column("raw_risk_score", existing_type=sa.Float(), type_=sa.Numeric(7, 3), existing_nullable=False)
        b.alter_column("calibrated_probability", existing_type=sa.Float(), type_=sa.Numeric(7, 5),
                       existing_nullable=False)
        b.add_column(sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("score_kind", sa.String(40), nullable=False, server_default="uncalibrated_v1"))
        b.add_column(sa.Column("policy_version", sa.String(50), nullable=False,
                               server_default="yogii-prototype-policy-v1"))
        b.add_column(sa.Column("thresholds_json", sa.Text(), nullable=False, server_default="{}"))
        b.add_column(sa.Column("graph_depth", sa.Integer(), nullable=False, server_default="2"))
        b.add_column(sa.Column("history_window_days", sa.Integer(), nullable=False, server_default="30"))
    op.execute("UPDATE risk_assessments SET risk_score = CAST(ROUND(raw_risk_score) AS INTEGER)")

    with op.batch_alter_table("feature_snapshots") as b:
        _tz(b, "feature_snapshots", "created_at")
        b.add_column(sa.Column("feature_schema_version", sa.String(20), nullable=False, server_default="v1"))
        b.create_index("ix_feature_snapshots_created_at", ["created_at"])

    # v1 graph edges used inconsistent node ids and can't be joined into chains; drop them.
    op.execute("DELETE FROM transaction_graph_edges")
    with op.batch_alter_table("transaction_graph_edges") as b:
        _tz(b, "transaction_graph_edges", "timestamp")
        b.alter_column("amount", existing_type=sa.Float(), type_=MONEY, existing_nullable=False)
        b.add_column(sa.Column("payment_type", sa.String(10), nullable=False, server_default="P2P"))
        b.create_index("ix_graph_receiver_time", ["receiver_node", "timestamp"])
        b.create_index("ix_graph_sender_time", ["sender_node", "timestamp"])
        b.create_index("ix_transaction_graph_edges_timestamp", ["timestamp"])
        b.create_unique_constraint("uq_graph_edge_payment", ["payment_id"])
        b.create_foreign_key("fk_graph_edge_payment", "payment_attempts", ["payment_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    with op.batch_alter_table("transaction_graph_edges") as b:
        b.drop_constraint("fk_graph_edge_payment", type_="foreignkey")
        b.drop_constraint("uq_graph_edge_payment", type_="unique")
        for ix in ("ix_transaction_graph_edges_timestamp", "ix_graph_sender_time", "ix_graph_receiver_time"):
            b.drop_index(ix)
        b.drop_column("payment_type")
        b.alter_column("amount", existing_type=MONEY, type_=sa.Float())
    with op.batch_alter_table("feature_snapshots") as b:
        b.drop_index("ix_feature_snapshots_created_at")
        b.drop_column("feature_schema_version")
    with op.batch_alter_table("risk_assessments") as b:
        for col in ("history_window_days", "graph_depth", "thresholds_json", "policy_version", "score_kind",
                    "risk_score"):
            b.drop_column(col)
    with op.batch_alter_table("payment_attempts") as b:
        b.drop_constraint("ck_payment_amount_positive", type_="check")
        b.drop_constraint("fk_payment_recipient_user", type_="foreignkey")
        b.drop_constraint("uq_payment_sender_auth_idempotency", type_="unique")
        b.drop_constraint("uq_payment_sender_idempotency", type_="unique")
        for ix in ("ix_payment_sender_created", "ix_payment_recipient_created", "ix_payment_attempts_recipient_user_id",
                   "ix_payment_attempts_provider_reference", "ix_payment_attempts_idempotency_key"):
            b.drop_index(ix)
        b.create_index("ix_payment_attempts_idempotency_key", ["idempotency_key"], unique=True)
        for col in ("completed_at", "location_hash", "device_hash", "balance_reversed", "balance_applied",
                    "verification_completed_at", "simulated_outcome", "authorization_idempotency_key",
                    "provider_reference", "decision", "note_enc", "recipient_name_enc", "recipient_upi_enc",
                    "recipient_user_id", "mode"):
            b.drop_column(col)
        b.alter_column("amount", existing_type=MONEY, type_=sa.Float())
    with op.batch_alter_table("recipients") as b:
        b.drop_index("ix_recipients_upi_id_lookup_hash")
        b.create_index("ix_recipients_upi_id_lookup_hash", ["upi_id_lookup_hash"], unique=False)
        b.drop_column("on_watchlist")
    with op.batch_alter_table("demo_payment_accounts") as b:
        b.drop_constraint("ck_demo_account_balance_nonnegative", type_="check")
        b.drop_column("is_simulated")
        b.alter_column("simulated_balance", existing_type=MONEY, type_=sa.Float())
    with op.batch_alter_table("users") as b:
        b.drop_index("ix_users_phone_lookup_hash")
        b.create_index("ix_users_phone_lookup_hash", ["phone_lookup_hash"], unique=False)
        for col in ("last_login_at", "is_fictional_demo", "token_version"):
            b.drop_column(col)
    with op.batch_alter_table("model_metadata") as b:
        b.drop_column("is_active")
        b.drop_column("is_synthetic")
    op.drop_index("ix_security_events_created_at", table_name="security_events")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_payment_state_transitions_payment_attempt_id", table_name="payment_state_transitions")
    op.drop_table("payment_state_transitions")
    op.drop_table("user_preferences")
    op.drop_index("ix_provider_callback_events_provider_reference", table_name="provider_callback_events")
    op.drop_table("provider_callback_events")
    # Timestamps stay timezone-aware on downgrade; that is compatible with the v1 code.
