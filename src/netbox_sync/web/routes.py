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
        cloud_result = request.app.state.cloud_fetcher()
        if (
            isinstance(cloud_result, tuple)
            and len(cloud_result) == 2
            and isinstance(cloud_result[1], list)
        ):
            cloud_vms, cloud_errors = cloud_result
            errors.extend(cloud_errors)
        else:
            cloud_vms = list(cloud_result)
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

    zabbix_fetch_ok = True
    try:
        zabbix_hosts = request.app.state.zabbix_fetcher()
    except Exception:
        logger.exception("Failed to fetch Zabbix hosts")
        zabbix_hosts = []
        zabbix_fetch_ok = False
        errors.append("Failed to fetch Zabbix hosts")

    config: Config | None = request.app.state.config
    monitoring_configured = (
        config.zabbix_configured if config else False
    ) and zabbix_fetch_ok

    engine = ComparisonEngine()
    result = engine.compare(
        cloud_vms, netbox_vms, zabbix_hosts,
        monitoring_configured=monitoring_configured,
    )

    vms = result.all_vms

    if provider:
        provider_lower = provider.lower()
        vms = [
            vm for vm in vms
            if (vm.cloud_provider and vm.cloud_provider.lower() == provider_lower)
            or (not vm.cloud_provider and vm.discrepancies)
        ]

    if status == "discrepancies":
        vms = [vm for vm in vms if vm.discrepancies]

    if search:
        search_lower = search.lower()
        vms = [vm for vm in vms if search_lower in vm.vm_name.lower()]

    filtered = provider or status == "discrepancies" or search
    if filtered:
        total = len(vms)
        in_sync = sum(1 for v in vms if not v.discrepancies)
        summary = {
            "total": total,
            "in_sync": in_sync,
            "with_discrepancies": total - in_sync,
        }
    else:
        summary = result.summary

    htmx_request = request.headers.get("HX-Request") == "true"
    template_name = "comparison_table.html" if htmx_request else "comparison.html"

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "vms": vms,
            "summary": summary,
            "errors": errors,
            "monitoring_configured": monitoring_configured,
            "filters": {
                "provider": provider,
                "status": status,
                "search": search,
            },
        },
    )
