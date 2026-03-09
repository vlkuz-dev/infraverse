"""Comparison route for Infraverse web UI."""

from fastapi import APIRouter, Query, Request

from infraverse.comparison.diagnostics import compute_sync_reasons
from infraverse.comparison.engine import ComparisonEngine
from infraverse.comparison.models import ComparisonResult
from infraverse.db.models import SyncRun, VM, NetBoxHost
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
) -> tuple[ComparisonResult, dict[str, int], bool, bool]:
    """Load data from DB and run comparison engine.

    Monitoring presence is determined from MonitoringHost records in the DB,
    scoped by tenant when tenant_id is provided.

    Args:
        repo: Database repository.
        app_config: Application config (used to check if monitoring is configured).
        tenant_id: Optional tenant ID to scope comparison to.

    Returns:
        Tuple of (ComparisonResult, vm_name_to_id mapping, netbox_configured, monitoring_configured).
    """
    db_vms = repo.list_vms(tenant_id=tenant_id)

    # Load monitoring hosts scoped by tenant or globally
    if tenant_id is not None:
        db_hosts = repo.get_monitoring_hosts_by_tenant(tenant_id)
    else:
        db_hosts = repo.list_monitoring_hosts()

    # Load NetBox hosts scoped by tenant or globally
    if tenant_id is not None:
        db_netbox_hosts = repo.get_netbox_hosts_by_tenant(tenant_id)
    else:
        db_netbox_hosts = repo.list_netbox_hosts()

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
        all_hosts = repo.list_monitoring_hosts() if tenant_id is not None else db_hosts
        monitoring_configured = len(all_hosts) > 0

    engine = ComparisonEngine()
    result = engine.compare(
        cloud_vms=cloud_vms,
        netbox_vms=netbox_vms,
        monitoring_configured=monitoring_configured,
        netbox_configured=netbox_configured,
        monitored_vm_names=monitored_vm_names,
    )

    # Annotate VMState objects with monitoring exemption data from DB
    exempt_vms = {
        vm.name.lower(): vm.monitoring_exempt_reason
        for vm in db_vms if vm.monitoring_exempt
    }
    if exempt_vms:
        for state in result.all_vms:
            if state.vm_name.lower() in exempt_vms:
                state.is_monitoring_exempt = True
                state.monitoring_exempt_reason = exempt_vms[state.vm_name.lower()]
        # Re-compute discrepancies and summary since exempt flag changes results
        for state in result.all_vms:
            state.discrepancies = engine._compute_discrepancies(
                state,
                monitoring_configured=monitoring_configured,
                netbox_configured=netbox_configured,
            )
        result.summary = engine.build_summary(result.all_vms)

    return result, vm_name_to_id, netbox_configured, monitoring_configured


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
    elif status == "missing_from_monitoring":
        filtered = [
            s for s in filtered
            if s.in_cloud and not s.in_monitoring and not s.is_monitoring_exempt
        ]
    elif status == "monitoring_exempt":
        filtered = [s for s in filtered if s.is_monitoring_exempt]
    elif status == "in_cloud_only":
        filtered = [s for s in filtered if s.in_cloud and not s.in_netbox and not s.in_monitoring]

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


def _sync_run_to_banner(source: str, label: str, run: SyncRun | None) -> dict:
    """Build a sync status banner entry for a source."""
    if run is None:
        return {"source": source, "label": label, "status": "never", "time": None, "error": None}
    return {
        "source": source,
        "label": label,
        "status": run.status,
        "time": run.finished_at or run.started_at,
        "error": run.error_message,
    }


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

        result, vm_name_to_id, netbox_configured, monitoring_configured = _run_comparison(
            repo, app_config=app_config, tenant_id=selected_tenant_id,
            infraverse_config=infraverse_config,
        )
        providers = _get_providers(repo)

        # Query latest SyncRuns for diagnostics
        latest_netbox = repo.get_latest_sync_run_by_source("netbox", tenant_id=selected_tenant_id)
        latest_zabbix = repo.get_latest_sync_run_by_source("zabbix", tenant_id=selected_tenant_id)
        latest_sync_runs: dict[str, SyncRun | None] = {
            "netbox": latest_netbox,
            "zabbix": latest_zabbix,
        }

        # Build per-VM sync error map from cloud VMs
        db_vms = repo.list_vms(tenant_id=selected_tenant_id)
        vm_sync_errors = {
            vm.name: vm.last_sync_error
            for vm in db_vms
            if vm.last_sync_error
        }

        # Annotate sync reasons BEFORE filtering
        compute_sync_reasons(result.all_vms, latest_sync_runs, vm_sync_errors)

        # Build sync status banner entries
        sync_status = []
        if netbox_configured or latest_netbox is not None:
            sync_status.append(_sync_run_to_banner("netbox", "NetBox", latest_netbox))
        if monitoring_configured or latest_zabbix is not None:
            sync_status.append(_sync_run_to_banner("zabbix", "Мониторинг", latest_zabbix))

    result = _filter_results(result, provider=provider, status=status, search=search)

    return {
        "result": result,
        "providers": providers,
        "current_provider": provider or "",
        "current_status": status or "",
        "current_search": search or "",
        "netbox_configured": netbox_configured,
        "monitoring_configured": monitoring_configured,
        "vm_name_to_id": vm_name_to_id,
        "tenants": tenants,
        "selected_tenant_id": selected_tenant_id,
        "sync_status": sync_status,
    }


def _parse_tenant_id(raw: str | None) -> int | None:
    """Parse tenant_id from query param, treating empty string as None."""
    if not raw:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


@router.get("/comparison")
def comparison(
    request: Request,
    provider: str | None = None,
    status: str | None = None,
    search: str | None = None,
    tenant_id: str | None = Query(default=None),
):
    templates = get_templates()
    context = _build_context(request, provider, status, search, tenant_id=_parse_tenant_id(tenant_id))
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
    tenant_id: str | None = Query(default=None),
):
    templates = get_templates()
    context = _build_context(request, provider, status, search, tenant_id=_parse_tenant_id(tenant_id))

    return templates.TemplateResponse(
        request,
        "comparison_table.html",
        context,
    )
