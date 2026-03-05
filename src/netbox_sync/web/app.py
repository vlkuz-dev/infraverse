"""FastAPI application factory for NetBox sync web UI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from netbox_sync.config import Config
from netbox_sync.web.routes import router


def create_app(config: Config | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Application configuration. If None, provider status
                will show as unconfigured on the dashboard.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(title="NetBox Sync")

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.state.config = config
    app.include_router(router)

    return app
