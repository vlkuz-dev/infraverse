"""Dashboard route for Infraverse web UI."""

from fastapi import APIRouter, Query, Request

from infraverse.db.repository import Repository
from infraverse.web.app import get_templates

router = APIRouter()


@router.get("/")
def dashboard(request: Request, tenant_id: int | None = Query(default=None)):
    templates = get_templates()
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        repo = Repository(session)
        tenants = repo.list_tenants()

        # Validate tenant_id — fall back to None if not found
        selected_tenant_id = None
        if tenant_id is not None:
            tenant = repo.get_tenant(tenant_id)
            if tenant is not None:
                selected_tenant_id = tenant_id

        cloud_accounts = repo.list_cloud_accounts_by_tenant(selected_tenant_id) if selected_tenant_id else repo.list_cloud_accounts()
        vms = repo.get_all_vms(tenant_id=selected_tenant_id)
        sync_runs = repo.get_latest_sync_runs(
            limit=10, tenant_id=selected_tenant_id,
        )

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
            "selected_tenant_id": selected_tenant_id,
        },
    )
