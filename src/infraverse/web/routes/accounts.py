"""Cloud account routes for Infraverse web UI."""

from fastapi import APIRouter, Request

from infraverse.db.repository import Repository
from infraverse.web.app import get_templates
from infraverse.web.links import build_account_links

router = APIRouter()


@router.get("/accounts")
def accounts_list(request: Request):
    templates = get_templates()
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        repo = Repository(session)
        accounts = repo.list_cloud_accounts_with_tenants()

        # Group accounts by tenant and extract data while session is open
        grouped = {}
        for account in accounts:
            tenant_name = account.tenant.name if account.tenant else "No Tenant"
            if tenant_name not in grouped:
                grouped[tenant_name] = []
            vm_count = len(account.vms) if account.vms else 0
            grouped[tenant_name].append({
                "id": account.id,
                "name": account.name,
                "provider_type": account.provider_type,
                "vm_count": vm_count,
                "created_at": account.created_at,
            })

    return templates.TemplateResponse(
        request,
        "accounts_list.html",
        {
            "active_page": "accounts",
            "grouped_accounts": grouped,
            "total_accounts": sum(len(v) for v in grouped.values()),
        },
    )


@router.get("/accounts/{account_id}")
def account_detail(request: Request, account_id: int):
    templates = get_templates()
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        repo = Repository(session)
        account = repo.get_cloud_account_with_tenant(account_id)
        if account is None:
            return templates.TemplateResponse(
                request,
                "404.html",
                {"active_page": "", "message": "Cloud account not found"},
                status_code=404,
            )

        vms = repo.get_vms_by_account(account_id)
        sync_runs = repo.get_sync_runs_by_account(account_id, limit=10)

        # Extract data while session is open
        account_data = {
            "id": account.id,
            "name": account.name,
            "provider_type": account.provider_type,
            "config": account.config or {},
            "created_at": account.created_at,
            "updated_at": account.updated_at,
        }
        tenant_data = None
        if account.tenant:
            tenant_data = {
                "id": account.tenant.id,
                "name": account.tenant.name,
            }

        vm_list = []
        active_count = 0
        offline_count = 0
        for vm in vms:
            vm_list.append({
                "id": vm.id,
                "name": vm.name,
                "status": vm.status,
                "ip_addresses": vm.ip_addresses or [],
                "vcpus": vm.vcpus,
                "memory_mb": vm.memory_mb,
            })
            if vm.status == "active":
                active_count += 1
            elif vm.status == "offline":
                offline_count += 1

        run_list = []
        for run in sync_runs:
            run_list.append({
                "id": run.id,
                "source": run.source,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "items_found": run.items_found,
                "items_created": run.items_created,
                "items_updated": run.items_updated,
                "error_message": run.error_message,
            })

    app_config = getattr(request.app.state, "config", None)
    external_links = build_account_links(account_data, app_config)

    return templates.TemplateResponse(
        request,
        "account_detail.html",
        {
            "active_page": "",
            "account": account_data,
            "tenant": tenant_data,
            "vms": vm_list,
            "vm_count": len(vm_list),
            "active_count": active_count,
            "offline_count": offline_count,
            "sync_runs": run_list,
            "external_links": external_links,
        },
    )
