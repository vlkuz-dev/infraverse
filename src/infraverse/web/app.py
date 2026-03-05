"""FastAPI application factory for Infraverse web UI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from infraverse.db.engine import create_engine, create_session_factory, init_db

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def get_templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app(database_url: str = "sqlite:///infraverse.db") -> FastAPI:
    """Create and configure the FastAPI application."""
    engine = create_engine(database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    app = FastAPI(title="Infraverse", version="0.0.1")
    app.state.session_factory = session_factory
    app.state.engine = engine

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from infraverse.web.routes import router

    app.include_router(router)

    return app
