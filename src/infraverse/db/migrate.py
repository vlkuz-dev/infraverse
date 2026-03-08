"""Programmatic Alembic migration helpers."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def _get_alembic_config(database_url: str | None = None) -> Config:
    """Build Alembic Config pointing at the project's alembic.ini."""
    # Find alembic.ini relative to this file (src/infraverse/db/ -> project root)
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    ini_path = project_root / "alembic.ini"
    cfg = Config(str(ini_path))
    url = database_url or os.environ.get("DATABASE_URL", "sqlite:///infraverse.db")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def upgrade_head(database_url: str | None = None) -> None:
    """Run 'alembic upgrade head' — apply all pending migrations."""
    cfg = _get_alembic_config(database_url)
    command.upgrade(cfg, "head")


def stamp_head(database_url: str | None = None) -> None:
    """Run 'alembic stamp head' — mark DB as current without running migrations."""
    cfg = _get_alembic_config(database_url)
    command.stamp(cfg, "head")


def generate_revision(message: str, database_url: str | None = None) -> None:
    """Run 'alembic revision --autogenerate -m <message>' — create a new migration."""
    cfg = _get_alembic_config(database_url)
    command.revision(cfg, message=message, autogenerate=True)


def downgrade_one(database_url: str | None = None) -> None:
    """Run 'alembic downgrade -1' — roll back the last migration."""
    cfg = _get_alembic_config(database_url)
    command.downgrade(cfg, "-1")


def current(database_url: str | None = None) -> str | None:
    """Return the current Alembic revision, or None if unversioned."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine as sa_create_engine

    url = database_url or os.environ.get("DATABASE_URL", "sqlite:///infraverse.db")
    engine = sa_create_engine(url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        return ctx.get_current_revision()
