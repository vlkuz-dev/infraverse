"""FastAPI application factory for Infraverse web UI."""

import hashlib
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from infraverse import __version__
from infraverse.db.engine import create_engine, create_session_factory, init_db

logger = logging.getLogger(__name__)


def _resolve_session_secret(oidc) -> str:
    """Resolve session secret: SESSION_SECRET env > oidc.session_secret > OIDC-derived."""
    env_secret = os.getenv("SESSION_SECRET")
    if env_secret:
        return env_secret
    if oidc.session_secret:
        return oidc.session_secret
    return hashlib.sha256(
        b"infraverse-session:" + oidc.client_secret.encode()
    ).hexdigest()

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


_templates: Jinja2Templates | None = None


def _get_user_from_request(request):
    """Extract user dict from session, or None if unavailable."""
    try:
        return request.session.get("user")
    except Exception:
        return None


def _get_csrf_token_from_request(request):
    """Get CSRF token from session for template rendering."""
    try:
        return request.session.get("csrf_token", "")
    except Exception:
        return ""


def _make_localtime_filter(infraverse_config=None):
    if infraverse_config is not None and infraverse_config.timezone is not None:
        tz = infraverse_config.timezone
        offset_hours = tz.offset_hours
        tz_label = tz.resolved_label
    else:
        offset_hours = int(os.getenv("TZ_OFFSET_HOURS", "0"))
        tz_label = os.getenv("TZ_LABEL", f"UTC{offset_hours:+d}" if offset_hours else "UTC")
    offset = timedelta(hours=offset_hours)

    def localtime(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
        if dt is None:
            return "-"
        return f"{(dt + offset).strftime(fmt)} {tz_label}"

    return localtime


def get_templates(infraverse_config=None) -> Jinja2Templates:
    global _templates
    if _templates is None:
        _templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        _templates.env.globals["version"] = __version__
        _templates.env.globals["get_user"] = _get_user_from_request
        _templates.env.globals["csrf_token"] = _get_csrf_token_from_request
        _templates.env.filters["localtime"] = _make_localtime_filter(infraverse_config)
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
        from infraverse.web.csrf import CSRFMiddleware
        from infraverse.web.middleware import AuthMiddleware
        from infraverse.web.routes.auth import router as auth_router, setup_oauth

        oidc = infraverse_config.oidc
        app.state.oauth = setup_oauth(oidc)
        app.include_router(auth_router)
        # Middleware added first = innermost (closest to route handler).
        # Starlette processes in reverse order: Session -> Auth -> CSRF -> route.
        app.add_middleware(CSRFMiddleware)
        app.add_middleware(AuthMiddleware)
        session_secret = _resolve_session_secret(oidc)
        debug_mode = os.getenv("INFRAVERSE_DEBUG", "").lower() in ("1", "true", "yes")
        app.add_middleware(
            SessionMiddleware,
            secret_key=session_secret,
            max_age=session_max_age,
            https_only=not debug_mode,
            same_site="lax" if debug_mode else "strict",
        )

    if config is not None and config.sync_interval_minutes > 0:
        from infraverse.scheduler import SchedulerService

        app.state.scheduler = SchedulerService(
            session_factory, config, infraverse_config=infraverse_config,
        )
    else:
        app.state.scheduler = None

    # Initialize templates with config (for timezone etc.)
    get_templates(infraverse_config)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from infraverse.web.routes import router

    app.include_router(router)

    return app
