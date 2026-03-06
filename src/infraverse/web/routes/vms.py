"""VM detail route for Infraverse web UI."""

from fastapi import APIRouter, Request

from infraverse.db.repository import Repository
from infraverse.web.app import get_templates

router = APIRouter()


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
        }
        account_data = None
        tenant_data = None
        if vm.cloud_account:
            account_data = {
                "id": vm.cloud_account.id,
                "name": vm.cloud_account.name,
                "provider_type": vm.cloud_account.provider_type,
            }
            if vm.cloud_account.tenant:
                tenant_data = {
                    "id": vm.cloud_account.tenant.id,
                    "name": vm.cloud_account.tenant.name,
                }

    return templates.TemplateResponse(
        request,
        "vm_detail.html",
        {
            "active_page": "",
            "vm": vm_data,
            "account": account_data,
            "tenant": tenant_data,
        },
    )
