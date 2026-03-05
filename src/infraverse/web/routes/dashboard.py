"""Dashboard route for Infraverse web UI."""

from fastapi import APIRouter, Request

from infraverse.db.repository import Repository
from infraverse.web.app import get_templates

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    templates = get_templates()
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        repo = Repository(session)
        tenants = repo.list_tenants()
        cloud_accounts = repo.list_cloud_accounts()
        vms = repo.get_all_vms()
        sync_runs = repo.get_latest_sync_runs(limit=10)

    total_vms = len(vms)
    active_vms = sum(1 for vm in vms if vm.status == "active")
    offline_vms = sum(1 for vm in vms if vm.status == "offline")

    provider_summary = {}
    for account in cloud_accounts:
        ptype = account.provider_type
        if ptype not in provider_summary:
            provider_summary[ptype] = {"count": 0, "accounts": []}
        provider_summary[ptype]["count"] += 1
        provider_summary[ptype]["accounts"].append(account)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_page": "dashboard",
            "tenants": tenants,
            "cloud_accounts": cloud_accounts,
            "total_vms": total_vms,
            "active_vms": active_vms,
            "offline_vms": offline_vms,
            "provider_summary": provider_summary,
            "sync_runs": sync_runs,
        },
    )
