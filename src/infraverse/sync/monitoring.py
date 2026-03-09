"""Per-VM monitoring check logic.

Bulk-fetches all Zabbix hosts once, then matches VMs locally by name
and IP address.  Falls back to per-VM API queries when bulk fetch fails.
"""

import logging
from dataclasses import dataclass
from typing import Any

from infraverse.providers.zabbix import ZabbixHost

logger = logging.getLogger(__name__)


@dataclass
class MonitoringResult:
    """Result of checking a single VM's monitoring status."""

    vm_name: str
    found: bool
    host: ZabbixHost | None = None
    matched_by: str | None = None  # "name" or "ip"


def _build_host_lookups(
    hosts: list[ZabbixHost],
) -> tuple[dict[str, ZabbixHost], dict[str, ZabbixHost]]:
    """Build name and IP lookup dicts from a list of ZabbixHost.

    Returns:
        (hosts_by_name, hosts_by_ip) — first match wins for duplicate keys.
    """
    by_name: dict[str, ZabbixHost] = {}
    by_ip: dict[str, ZabbixHost] = {}
    for h in hosts:
        by_name.setdefault(h.name, h)
        for ip in h.ip_addresses:
            by_ip.setdefault(ip, h)
    return by_name, by_ip


def _check_vm_from_lookups(
    vm: Any,
    hosts_by_name: dict[str, ZabbixHost],
    hosts_by_ip: dict[str, ZabbixHost],
) -> MonitoringResult:
    """Match a VM against pre-built lookup dicts (name first, then IP)."""
    host = hosts_by_name.get(vm.name)
    if host is not None:
        return MonitoringResult(
            vm_name=vm.name, found=True, host=host, matched_by="name"
        )

    for ip in vm.ip_addresses or []:
        host = hosts_by_ip.get(ip)
        if host is not None:
            return MonitoringResult(
                vm_name=vm.name, found=True, host=host, matched_by="ip"
            )

    return MonitoringResult(vm_name=vm.name, found=False)


def check_vm_monitoring(vm: Any, zabbix_client: Any) -> MonitoringResult:
    """Check if a VM is monitored in Zabbix (per-VM API fallback).

    Tries name match first, then falls back to checking each IP address.

    Args:
        vm: VM object with .name and .ip_addresses attributes.
        zabbix_client: ZabbixClient with search_host_by_name/ip methods.

    Returns:
        MonitoringResult with found status and host details.

    Raises:
        RuntimeError: On Zabbix API errors.
    """
    host = zabbix_client.search_host_by_name(vm.name)
    if host is not None:
        return MonitoringResult(
            vm_name=vm.name, found=True, host=host, matched_by="name"
        )

    ips = vm.ip_addresses or []
    for ip in ips:
        host = zabbix_client.search_host_by_ip(ip)
        if host is not None:
            return MonitoringResult(
                vm_name=vm.name, found=True, host=host, matched_by="ip"
            )

    return MonitoringResult(vm_name=vm.name, found=False)


def check_all_vms_monitoring(
    vms: list[Any], zabbix_client: Any
) -> list[MonitoringResult]:
    """Check monitoring status for a batch of VMs.

    Tries a single bulk fetch of all Zabbix hosts first, then matches
    locally.  Falls back to per-VM API queries if bulk fetch fails.

    Args:
        vms: List of VM objects.
        zabbix_client: ZabbixClient instance.

    Returns:
        List of MonitoringResult, one per input VM, in the same order.
    """
    if not vms:
        return []

    # Try bulk fetch for O(1) lookups instead of per-VM API calls.
    hosts_by_name: dict[str, ZabbixHost] | None = None
    hosts_by_ip: dict[str, ZabbixHost] | None = None
    bulk_truncated = False
    try:
        all_hosts = zabbix_client.fetch_hosts()
        hosts_by_name, hosts_by_ip = _build_host_lookups(all_hosts)
        bulk_truncated = getattr(zabbix_client, "last_fetch_truncated", False)
        logger.info(
            "Bulk-fetched %d Zabbix hosts for monitoring lookup%s",
            len(all_hosts),
            " (truncated, will use per-VM fallback for misses)" if bulk_truncated else "",
        )
    except Exception as exc:
        logger.warning(
            "Bulk Zabbix fetch failed, falling back to per-VM queries: %s", exc
        )

    results = []
    for vm in vms:
        try:
            if hosts_by_name is not None and hosts_by_ip is not None:
                result = _check_vm_from_lookups(vm, hosts_by_name, hosts_by_ip)
                # When bulk data is truncated, VMs not found in the partial
                # dataset may still exist beyond the pagination limit.
                # Fall back to per-VM API queries for those VMs.
                if not result.found and bulk_truncated:
                    result = check_vm_monitoring(vm, zabbix_client)
            else:
                result = check_vm_monitoring(vm, zabbix_client)
        except Exception as exc:
            logger.warning("Failed to check monitoring for VM %s: %s", vm.name, exc)
            result = MonitoringResult(vm_name=vm.name, found=False)
        results.append(result)
        if result.found:
            logger.debug(
                "VM %s: monitored (matched by %s, hostid=%s)",
                vm.name, result.matched_by, result.host.hostid,
            )
        else:
            logger.debug("VM %s: not monitored", vm.name)
    return results
