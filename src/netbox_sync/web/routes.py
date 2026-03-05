"""Web routes for the NetBox sync dashboard."""

import logging
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from netbox_sync.comparison.engine import ComparisonEngine
from netbox_sync.config import Config

logger = logging.getLogger(__name__)

router = APIRouter()

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Render the main dashboard page with provider status and summary."""
    config: Config | None = request.app.state.config

    providers = []
    if config:
        providers.append({"name": "Yandex Cloud", "configured": True})
        providers.append({
            "name": "vCloud Director",
            "configured": config.vcd_configured,
        })
        providers.append({
            "name": "Zabbix",
            "configured": config.zabbix_configured,
        })

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "providers": providers,
            "summary": {
                "total_providers": sum(1 for p in providers if p["configured"]),
                "configured_providers": providers,
            },
        },
    )


@router.get("/comparison", response_class=HTMLResponse)
def comparison(
    request: Request,
    provider: str = Query(default="", description="Filter by cloud provider"),
    status: str = Query(default="all", description="Filter: all or discrepancies"),
    search: str = Query(default="", description="Filter by VM name substring"),
):
    """Run comparison engine and render results."""
    errors: list[str] = []

    try:
        cloud_vms = request.app.state.cloud_fetcher()
    except Exception:
        logger.exception("Failed to fetch cloud VMs")
        cloud_vms = []
        errors.append("Failed to fetch cloud VMs")

    try:
        netbox_vms = request.app.state.netbox_fetcher()
    except Exception:
        logger.exception("Failed to fetch NetBox VMs")
        netbox_vms = []
        errors.append("Failed to fetch NetBox VMs")

    try:
        zabbix_hosts = request.app.state.zabbix_fetcher()
    except Exception:
        logger.exception("Failed to fetch Zabbix hosts")
        zabbix_hosts = []
        errors.append("Failed to fetch Zabbix hosts")

    engine = ComparisonEngine()
    result = engine.compare(cloud_vms, netbox_vms, zabbix_hosts)

    vms = result.all_vms

    if provider:
        provider_lower = provider.lower()
        vms = [
            vm for vm in vms
            if vm.cloud_provider and vm.cloud_provider.lower() == provider_lower
        ]

    if status == "discrepancies":
        vms = [vm for vm in vms if vm.discrepancies]

    if search:
        search_lower = search.lower()
        vms = [vm for vm in vms if search_lower in vm.vm_name.lower()]

    htmx_request = request.headers.get("HX-Request") == "true"
    template_name = "comparison_table.html" if htmx_request else "comparison.html"

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "vms": vms,
            "summary": result.summary,
            "errors": errors,
            "filters": {
                "provider": provider,
                "status": status,
                "search": search,
            },
        },
    )
