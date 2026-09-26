"""Tighten the application role: audit history is append-only.

Revision ID: 0003_app_role_grants
Revises: 0002_v2_schema
Create Date: 2026-09-26

Only applies on PostgreSQL when the `yogii_app` role exists (created by
infrastructure/postgres/init/01-roles.sh). The API can add audit and security
events but can't change or delete them; retention runs with the migrator role.
"""
from alembic import op

revision = "0003_app_role_grants"
down_revision = "0002_v2_schema"
branch_labels = None
depends_on = None

APPEND_ONLY = ("audit_events", "security_events", "payment_state_transitions", "provider_callback_events",
               "risk_assessments", "feature_snapshots")


def _app_role_exists() -> bool:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    return bool(bind.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = 'yogii_app'").scalar())


def upgrade() -> None:
    if _app_role_exists():
        for table in APPEND_ONLY:
            op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM yogii_app")


def downgrade() -> None:
    if _app_role_exists():
        for table in APPEND_ONLY:
            op.execute(f"GRANT UPDATE, DELETE ON {table} TO yogii_app")
