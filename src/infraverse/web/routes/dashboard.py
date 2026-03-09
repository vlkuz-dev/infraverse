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

        cloud_accounts = repo.list_cloud_accounts(tenant_id=selected_tenant_id)
        vms = repo.list_vms(tenant_id=selected_tenant_id)
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


@router.get("/dashboard/vm-table")
def dashboard_vm_table(
    request: Request,
    status: str | None = Query(default=None),
    tenant_id: str = Query(default=""),
):
    templates = get_templates()
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        repo = Repository(session)

        selected_tenant_id = None
        if tenant_id.isdigit():
            tenant = repo.get_tenant(int(tenant_id))
            if tenant is not None:
                selected_tenant_id = tenant.id

        selected_status = status if status in ("active", "offline") else None

        vms = repo.list_vms(
            tenant_id=selected_tenant_id,
            status=selected_status,
        )

        vm_list_data = []
        for vm in vms:
            account_name = ""
            if vm.cloud_account:
                account_name = vm.cloud_account.name
            vm_list_data.append({
                "id": vm.id,
                "name": vm.name,
                "status": vm.status,
                "ip_addresses": vm.ip_addresses or [],
                "vcpus": vm.vcpus,
                "memory_mb": vm.memory_mb,
                "account_name": account_name,
            })

    if selected_status == "active":
        table_title = "Active VMs"
    elif selected_status == "offline":
        table_title = "Offline VMs"
    else:
        table_title = "All VMs"

    return templates.TemplateResponse(
        request,
        "dashboard_vm_table.html",
        {
            "vms": vm_list_data,
            "table_title": table_title,
        },
    )
