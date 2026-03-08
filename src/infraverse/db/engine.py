"""Database engine and session management."""

import logging

from sqlalchemy import create_engine as sa_create_engine
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


def init_db(engine) -> None:
    """Create all database tables from model metadata.

    For production use, prefer 'alembic upgrade head' via the db init CLI command.
    This function is kept for test fixtures and as a safety net for code paths
    that create tables directly (e.g. web app startup).
    """
    Base.metadata.create_all(bind=engine)
