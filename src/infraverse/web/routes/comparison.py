"""Comparison route for Infraverse web UI."""

from fastapi import APIRouter, Request

from infraverse.comparison.engine import ComparisonEngine
from infraverse.comparison.models import ComparisonResult
from infraverse.db.models import VM, MonitoringHost
from infraverse.db.repository import Repository
from infraverse.providers.base import VMInfo
from infraverse.providers.zabbix import ZabbixHost
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


def _host_to_zabbixhost(host: MonitoringHost) -> ZabbixHost:
    """Convert a DB MonitoringHost record to a ZabbixHost dataclass."""
    return ZabbixHost(
        name=host.name,
        hostid=host.external_id,
        status=host.status,
        ip_addresses=host.ip_addresses or [],
    )


def _run_comparison(repo: Repository) -> ComparisonResult:
    """Load data from DB and run comparison engine."""
    db_vms = repo.get_all_vms()
    db_hosts = repo.get_all_monitoring_hosts()

    cloud_vms = [_vm_to_vminfo(vm) for vm in db_vms]
    zabbix_hosts = [_host_to_zabbixhost(h) for h in db_hosts]

    monitoring_configured = len(zabbix_hosts) > 0

    engine = ComparisonEngine()
    return engine.compare(
        cloud_vms=cloud_vms,
        netbox_vms=[],
        zabbix_hosts=zabbix_hosts,
        monitoring_configured=monitoring_configured,
        netbox_configured=False,
    )


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


def _build_context(request: Request, provider, status, search):
    """Shared logic for comparison and comparison_table routes."""
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        repo = Repository(session)
        result = _run_comparison(repo)
        providers = _get_providers(repo)

    result = _filter_results(result, provider=provider, status=status, search=search)

    return {
        "result": result,
        "providers": providers,
        "current_provider": provider or "",
        "current_status": status or "",
        "current_search": search or "",
        "netbox_configured": False,
    }


@router.get("/comparison")
def comparison(
    request: Request,
    provider: str | None = None,
    status: str | None = None,
    search: str | None = None,
):
    templates = get_templates()
    context = _build_context(request, provider, status, search)
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
):
    templates = get_templates()
    context = _build_context(request, provider, status, search)

    return templates.TemplateResponse(
        request,
        "comparison_table.html",
        context,
    )
