"""Alembic migrations produce exactly the schema the models describe."""

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from sqlalchemy import create_engine

from backend.database.database import Base


def test_upgrade_matches_models_and_downgrade_works(tmp_path):
    url = f"sqlite:///{tmp_path}/migrate.db"
    cfg = Config("alembic.ini")
    cfg.cmd_opts = type("Opts", (), {"x": [f"url={url}"]})()
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], diff
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
