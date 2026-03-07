"""Database engine and session management."""

import logging

from sqlalchemy import create_engine as sa_create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from infraverse.db.models import Base

logger = logging.getLogger(__name__)


def create_engine(database_url: str = "sqlite:///infraverse.db"):
    """Create a SQLAlchemy engine."""
    connect_args = {}
    kwargs = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
    return sa_create_engine(database_url, connect_args=connect_args, **kwargs)


def create_session_factory(engine) -> sessionmaker:
    """Create a session factory bound to the given engine."""
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _migrate_schema(engine) -> None:
    """Apply lightweight schema migrations for columns added after initial release."""
    insp = inspect(engine)
    if "netbox_hosts" in insp.get_table_names():
        columns = {c["name"] for c in insp.get_columns("netbox_hosts")}
        if "tenant_id" not in columns:
            logger.info("Migrating netbox_hosts: adding tenant_id column")
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE netbox_hosts ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)")
                )


def init_db(engine) -> None:
    """Create all database tables and apply pending migrations."""
    Base.metadata.create_all(bind=engine)
    _migrate_schema(engine)
