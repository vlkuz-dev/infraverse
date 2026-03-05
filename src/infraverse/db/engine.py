"""Database engine and session management."""

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import sessionmaker, Session

from infraverse.db.models import Base


def create_engine(database_url: str = "sqlite:///infraverse.db"):
    """Create a SQLAlchemy engine."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return sa_create_engine(database_url, connect_args=connect_args)


def create_session_factory(engine) -> sessionmaker:
    """Create a session factory bound to the given engine."""
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def init_db(engine) -> None:
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
