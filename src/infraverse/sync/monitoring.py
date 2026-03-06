"""Per-VM monitoring check logic.

Instead of bulk-fetching all Zabbix hosts, this module queries Zabbix
per known VM to check monitoring presence: name match first, then
IP fallback.
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from infraverse.providers.zabbix import ZabbixHost

logger = logging.getLogger(__name__)


class VMlike(Protocol):
    """Protocol for VM-like objects (DB model or test fake)."""

    name: str
    ip_addresses: list[str] | None


class ZabbixClientlike(Protocol):
    """Protocol for ZabbixClient-like objects."""

    def search_host_by_name(self, name: str) -> ZabbixHost | None: ...
    def search_host_by_ip(self, ip: str) -> ZabbixHost | None: ...


@dataclass
class MonitoringResult:
    """Result of checking a single VM's monitoring status."""

    vm_name: str
    found: bool
    host: ZabbixHost | None = None
    matched_by: str | None = None  # "name" or "ip"


def check_vm_monitoring(vm: Any, zabbix_client: Any) -> MonitoringResult:
    """Check if a VM is monitored in Zabbix.

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

    Args:
        vms: List of VM objects.
        zabbix_client: ZabbixClient instance.

    Returns:
        List of MonitoringResult, one per input VM, in the same order.
    """
    results = []
    for vm in vms:
        result = check_vm_monitoring(vm, zabbix_client)
        results.append(result)
        if result.found:
            logger.debug(
                "VM %s: monitored (matched by %s, hostid=%s)",
                vm.name, result.matched_by, result.host.hostid,
            )
        else:
            logger.debug("VM %s: not monitored", vm.name)
    return results
