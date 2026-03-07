"""Comparison route for Infraverse web UI."""

from fastapi import APIRouter, Query, Request

from infraverse.comparison.engine import ComparisonEngine
from infraverse.comparison.models import ComparisonResult
from infraverse.db.models import VM, NetBoxHost
from infraverse.db.repository import Repository
from infraverse.providers.base import VMInfo
from infraverse.web.app import get_templates

router = APIRouter()


def _vm_to_vminfo(vm: VM) -> VMInfo:
    """Convert a DB VM record to a VMInfo dataclass."""
    return VMInfo(
        name=vm.name,
        id=vm.external_id,
        status=vm.status,
        ip_addresses=vm.ip_addresses or [],
        vcpus=vm.vcpus or 0,
        memory_mb=vm.memory_mb or 0,
        provider=vm.cloud_account.provider_type if vm.cloud_account else "",
        cloud_name=vm.cloud_name or "",
        folder_name=vm.folder_name or "",
    )


def _netbox_host_to_vminfo(host: NetBoxHost) -> VMInfo:
    """Convert a DB NetBoxHost record to a VMInfo dataclass."""
    return VMInfo(
        name=host.name,
        id=host.external_id,
        status=host.status,
        ip_addresses=host.ip_addresses or [],
        vcpus=host.vcpus or 0,
        memory_mb=host.memory_mb or 0,
        provider="netbox",
        cloud_name="",
        folder_name=host.cluster_name or "",
    )


def _run_comparison(
    repo: Repository,
    app_config=None,
    tenant_id: int | None = None,
    infraverse_config=None,
) -> tuple[ComparisonResult, dict[str, int]]:
    """Load data from DB and run comparison engine.

    Monitoring presence is determined from MonitoringHost records in the DB,
    scoped by tenant when tenant_id is provided.

    Args:
        repo: Database repository.
        app_config: Application config (used to check if monitoring is configured).
        tenant_id: Optional tenant ID to scope comparison to.

    Returns:
        Tuple of (ComparisonResult, vm_name_to_id mapping).
    """
    db_vms = repo.get_all_vms(tenant_id=tenant_id)

    # Load monitoring hosts scoped by tenant or globally
    if tenant_id is not None:
        db_hosts = repo.get_monitoring_hosts_by_tenant(tenant_id)
    else:
        db_hosts = repo.get_all_monitoring_hosts()

    # Load NetBox hosts from DB
    db_netbox_hosts = repo.get_all_netbox_hosts()

    # NOTE: keeps first ID per name; duplicate names across accounts link to the same detail page
    vm_name_to_id: dict[str, int] = {}
    for vm in db_vms:
        if vm.name not in vm_name_to_id:
            vm_name_to_id[vm.name] = vm.id
    cloud_vms = [_vm_to_vminfo(vm) for vm in db_vms]

    # Build set of monitored VM names from MonitoringHost records
    monitored_vm_names = {h.name for h in db_hosts}

    # Build NetBox VM list from NetBoxHost records
    netbox_vms = [_netbox_host_to_vminfo(h) for h in db_netbox_hosts]
    netbox_configured = len(db_netbox_hosts) > 0

    # Use config to determine if monitoring is configured; fall back to global data presence
    if infraverse_config is not None and infraverse_config.monitoring_configured:
        monitoring_configured = True
    elif app_config is not None and hasattr(app_config, "zabbix_configured"):
        monitoring_configured = app_config.zabbix_configured
    else:
        # Check global monitoring hosts (not tenant-scoped) to detect if monitoring is set up
        all_hosts = repo.get_all_monitoring_hosts() if tenant_id is not None else db_hosts
        monitoring_configured = len(all_hosts) > 0

    engine = ComparisonEngine()
    result = engine.compare(
        cloud_vms=cloud_vms,
        netbox_vms=netbox_vms,
        monitoring_configured=monitoring_configured,
        netbox_configured=netbox_configured,
        monitored_vm_names=monitored_vm_names,
    )
    return result, vm_name_to_id, netbox_configured


def _filter_results(
    result: ComparisonResult,
    provider: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> ComparisonResult:
    """Apply filters to comparison results."""
    filtered = result.all_vms

    if provider:
        filtered = [
            s for s in filtered
            if s.cloud_provider and s.cloud_provider == provider
        ]

    if status == "in_sync":
        filtered = [s for s in filtered if not s.discrepancies]
    elif status == "with_issues":
        filtered = [s for s in filtered if s.discrepancies]
    elif status == "missing_from_netbox":
        filtered = [s for s in filtered if s.in_cloud and not s.in_netbox]
    elif status == "missing_from_cloud":
        filtered = [s for s in filtered if s.in_netbox and not s.in_cloud]

    if search:
        search_lower = search.lower()
        filtered = [s for s in filtered if search_lower in s.vm_name.lower()]

    engine = ComparisonEngine()
    summary = engine.build_summary(filtered)
    return ComparisonResult(all_vms=filtered, summary=summary)


def _get_providers(repo: Repository) -> list[str]:
    """Get distinct provider types from cloud accounts."""
    accounts = repo.list_cloud_accounts()
    return sorted({a.provider_type for a in accounts})


def _build_context(request: Request, provider, status, search, tenant_id=None):
    """Shared logic for comparison and comparison_table routes."""
    app_config = getattr(request.app.state, "config", None)
    infraverse_config = getattr(request.app.state, "infraverse_config", None)
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

        result, vm_name_to_id, netbox_configured = _run_comparison(
            repo, app_config=app_config, tenant_id=selected_tenant_id,
            infraverse_config=infraverse_config,
        )
        providers = _get_providers(repo)

    result = _filter_results(result, provider=provider, status=status, search=search)

    return {
        "result": result,
        "providers": providers,
        "current_provider": provider or "",
        "current_status": status or "",
        "current_search": search or "",
        "netbox_configured": netbox_configured,
        "vm_name_to_id": vm_name_to_id,
        "tenants": tenants,
        "selected_tenant_id": selected_tenant_id,
    }


@router.get("/comparison")
def comparison(
    request: Request,
    provider: str | None = None,
    status: str | None = None,
    search: str | None = None,
    tenant_id: int | None = Query(default=None),
):
    templates = get_templates()
    context = _build_context(request, provider, status, search, tenant_id=tenant_id)
    context["active_page"] = "comparison"

    return templates.TemplateResponse(
        request,
        "comparison.html",
        context,
    )


@router.get("/comparison/table")
def comparison_table(
    request: Request,
    provider: str | None = None,
    status: str | None = None,
    search: str | None = None,
    tenant_id: int | None = Query(default=None),
):
    templates = get_templates()
    context = _build_context(request, provider, status, search, tenant_id=tenant_id)

    return templates.TemplateResponse(
        request,
        "comparison_table.html",
        context,
    )
