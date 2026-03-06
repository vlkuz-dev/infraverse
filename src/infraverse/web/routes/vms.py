"""VM list and detail routes for Infraverse web UI."""

from fastapi import APIRouter, Query, Request

from infraverse.db.repository import Repository
from infraverse.web.app import get_templates
from infraverse.web.links import build_vm_links

router = APIRouter()


@router.get("/vms")
def vm_list(
    request: Request,
    tenant_id: int | None = Query(default=None),
    account_id: int | None = Query(default=None),
):
    templates = get_templates()
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        repo = Repository(session)
        tenants = repo.list_tenants()

        # Validate tenant_id
        selected_tenant_id = None
        if tenant_id is not None:
            tenant = repo.get_tenant(tenant_id)
            if tenant is not None:
                selected_tenant_id = tenant_id

        # Validate account_id
        selected_account_id = None
        if account_id is not None:
            account = repo.get_cloud_account(account_id)
            if account is not None:
                selected_account_id = account_id

        vms = repo.get_all_vms(
            tenant_id=selected_tenant_id,
            account_id=selected_account_id,
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

    return templates.TemplateResponse(
        request,
        "vm_list.html",
        {
            "active_page": "vms",
            "vms": vm_list_data,
            "vm_count": len(vm_list_data),
            "tenants": tenants,
            "selected_tenant_id": selected_tenant_id,
            "selected_account_id": selected_account_id,
        },
    )


@router.get("/vms/{vm_id}")
def vm_detail(request: Request, vm_id: int):
    templates = get_templates()
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        repo = Repository(session)
        vm = repo.get_vm_by_id(vm_id)
        if vm is None:
            return templates.TemplateResponse(
                request,
                "404.html",
                {"active_page": "", "message": "VM not found"},
                status_code=404,
            )

        # Extract data while session is open (relationships loaded)
        # Look up matching monitoring host for external link building
        monitoring_host = repo.get_monitoring_host_by_name(vm.name)
        vm_data = {
            "id": vm.id,
            "name": vm.name,
            "external_id": vm.external_id,
            "status": vm.status,
            "ip_addresses": vm.ip_addresses or [],
            "vcpus": vm.vcpus,
            "memory_mb": vm.memory_mb,
            "cloud_name": vm.cloud_name,
            "folder_name": vm.folder_name,
            "created_at": vm.created_at,
            "updated_at": vm.updated_at,
            "last_seen_at": vm.last_seen_at,
            "monitoring_host_id": monitoring_host.external_id if monitoring_host else "",
        }
        account_data = None
        tenant_data = None
        if vm.cloud_account:
            account_data = {
                "id": vm.cloud_account.id,
                "name": vm.cloud_account.name,
                "provider_type": vm.cloud_account.provider_type,
                "config": vm.cloud_account.config or {},
            }
            if vm.cloud_account.tenant:
                tenant_data = {
                    "id": vm.cloud_account.tenant.id,
                    "name": vm.cloud_account.tenant.name,
                }

    app_config = getattr(request.app.state, "config", None)
    external_links = build_vm_links(vm_data, account_data, app_config)

    return templates.TemplateResponse(
        request,
        "vm_detail.html",
        {
            "active_page": "",
            "vm": vm_data,
            "account": account_data,
            "tenant": tenant_data,
            "external_links": external_links,
        },
    )
