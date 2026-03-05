"""FastAPI application factory for NetBox sync web UI."""

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from netbox_sync.clients.base import VMInfo
from netbox_sync.clients.zabbix import ZabbixHost
from netbox_sync.config import Config
from netbox_sync.web.routes import router


def create_app(
    config: Config | None = None,
    cloud_fetcher: Callable[[], list[VMInfo] | tuple[list[VMInfo], list[str]]] | None = None,
    netbox_fetcher: Callable[[], list[VMInfo]] | None = None,
    zabbix_fetcher: Callable[[], list[ZabbixHost]] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Application configuration. If None, provider status
                will show as unconfigured on the dashboard.
        cloud_fetcher: Callable returning cloud VMs for comparison.
            May return ``list[VMInfo]`` or ``(list[VMInfo], list[str])``
            where the second element contains per-provider error messages.
        netbox_fetcher: Callable returning NetBox VMs for comparison.
        zabbix_fetcher: Callable returning Zabbix hosts for comparison.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(title="NetBox Sync")

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.state.config = config
    app.state.cloud_fetcher = cloud_fetcher or (lambda: [])
    app.state.netbox_fetcher = netbox_fetcher or (lambda: [])
    app.state.zabbix_fetcher = zabbix_fetcher or (lambda: [])
    app.include_router(router)

    return app
