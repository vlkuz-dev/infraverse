"""Web routes for the NetBox sync dashboard."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from netbox_sync.config import Config

router = APIRouter()

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
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
