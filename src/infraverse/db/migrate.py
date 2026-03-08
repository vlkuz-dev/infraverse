"""Programmatic Alembic migration helpers."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def _get_alembic_config(database_url: str | None = None) -> Config:
    """Build Alembic Config pointing at the package's migration scripts.

    Resolves the migrations directory relative to this file so it works both
    in a development checkout and in an installed package (pip / Docker).
    """
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    cfg = Config()
    # Ensure the [alembic] section exists for programmatic configuration
    if not cfg.file_config.has_section(cfg.config_ini_section):
        cfg.file_config.add_section(cfg.config_ini_section)
    cfg.set_main_option("script_location", str(migrations_dir))
    url = database_url or os.environ.get("DATABASE_URL", "sqlite:///infraverse.db")
    cfg.set_main_option("sqlalchemy.url", url)
    # Prevent env.py from calling fileConfig() which reconfigures Python logging
    cfg.config_file_name = None
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

    cfg = _get_alembic_config(database_url)
    url = cfg.get_main_option("sqlalchemy.url")
    engine = sa_create_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            return ctx.get_current_revision()
    finally:
        engine.dispose()
