"""Database engine and session management."""

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from infraverse.db.models import Base


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
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
