"""FastAPI application factory for Infraverse web UI."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from infraverse import __version__
from infraverse.db.engine import create_engine, create_session_factory, init_db

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


_templates: Jinja2Templates | None = None


def get_templates() -> Jinja2Templates:
    global _templates
    if _templates is None:
        _templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        _templates.env.globals["version"] = __version__
    return _templates


@asynccontextmanager
async def lifespan(app):
    """Manage application lifespan: start/stop scheduler if configured."""
    if hasattr(app.state, "scheduler") and app.state.scheduler is not None:
        config = app.state.config
        if config.sync_interval_minutes > 0:
            app.state.scheduler.start(config.sync_interval_minutes)
    yield
    if hasattr(app.state, "scheduler") and app.state.scheduler is not None:
        app.state.scheduler.stop()


def create_app(
    database_url: str = "sqlite:///infraverse.db",
    config=None,
    infraverse_config=None,
    session_max_age: int = 14 * 24 * 60 * 60,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    engine = create_engine(database_url)
    init_db(engine)
    session_factory = create_session_factory(engine)

    app = FastAPI(title="Infraverse", version=__version__, lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.engine = engine
    app.state.config = config
    app.state.infraverse_config = infraverse_config

    # Health endpoint (always accessible, no auth)
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # Set up OIDC auth if configured
    if infraverse_config is not None and infraverse_config.oidc_configured:
        from infraverse.web.middleware import AuthMiddleware
        from infraverse.web.routes.auth import router as auth_router, setup_oauth

        oidc = infraverse_config.oidc
        app.state.oauth = setup_oauth(oidc)
        app.include_router(auth_router)
        # Auth middleware must be added before session middleware
        # (Starlette processes middleware in reverse order of addition)
        app.add_middleware(AuthMiddleware)
        app.add_middleware(
            SessionMiddleware,
            secret_key=oidc.client_secret,
            max_age=session_max_age,
        )

    if config is not None and config.sync_interval_minutes > 0:
        from infraverse.scheduler import SchedulerService

        app.state.scheduler = SchedulerService(
            session_factory, config, infraverse_config=infraverse_config,
        )
    else:
        app.state.scheduler = None

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from infraverse.web.routes import router

    app.include_router(router)

    return app
