"""Comparison engine: cross-references cloud VMs, NetBox VMs, and Zabbix hosts."""

import logging

from netbox_sync.clients.base import VMInfo
from netbox_sync.clients.zabbix import ZabbixHost
from netbox_sync.comparison.models import ComparisonResult, VMState

logger = logging.getLogger(__name__)


class ComparisonEngine:
    """Compares VM presence across cloud providers, NetBox, and Zabbix."""

    def compare(
        self,
        cloud_vms: list[VMInfo],
        netbox_vms: list[VMInfo],
        zabbix_hosts: list[ZabbixHost],
    ) -> ComparisonResult:
        """Compare VMs across all three systems.

        Matching strategy:
        1. Primary: exact VM name match (case-insensitive)
        2. Secondary: shared IP address when names differ

        Args:
            cloud_vms: VMs from all cloud providers.
            netbox_vms: VMs from NetBox.
            zabbix_hosts: Hosts from Zabbix.

        Returns:
            ComparisonResult with per-VM state and summary.
        """
        # Build lookup structures (name lowercased -> source data)
        cloud_by_name: dict[str, VMInfo] = {}
        cloud_by_ip: dict[str, VMInfo] = {}
        for vm in cloud_vms:
            cloud_by_name[vm.name.lower()] = vm
            for ip in vm.ip_addresses:
                cloud_by_ip[ip] = vm

        netbox_by_name: dict[str, VMInfo] = {}
        netbox_by_ip: dict[str, VMInfo] = {}
        for vm in netbox_vms:
            netbox_by_name[vm.name.lower()] = vm
            for ip in vm.ip_addresses:
                netbox_by_ip[ip] = vm

        zabbix_by_name: dict[str, ZabbixHost] = {}
        zabbix_by_ip: dict[str, ZabbixHost] = {}
        for host in zabbix_hosts:
            zabbix_by_name[host.name.lower()] = host
            for ip in host.ip_addresses:
                zabbix_by_ip[ip] = host

        # Collect all unique VM names (case-insensitive)
        all_names: set[str] = set()
        all_names.update(cloud_by_name.keys())
        all_names.update(netbox_by_name.keys())
        all_names.update(zabbix_by_name.keys())

        # Track which entries from each source have been consumed by IP matching
        # to prevent double-counting (name lower -> True)
        ip_consumed_netbox: set[str] = set()
        ip_consumed_zabbix: set[str] = set()
        ip_consumed_cloud: set[str] = set()

        states: list[VMState] = []

        # Phase 1: Name-based matching
        for name in sorted(all_names):
            cloud_vm = cloud_by_name.get(name)
            netbox_vm = netbox_by_name.get(name)
            zabbix_host = zabbix_by_name.get(name)

            # Use original casing from whichever source has it
            display_name = name
            if cloud_vm:
                display_name = cloud_vm.name
            elif netbox_vm:
                display_name = netbox_vm.name
            elif zabbix_host:
                display_name = zabbix_host.name

            state = VMState(
                vm_name=display_name,
                in_cloud=cloud_vm is not None,
                in_netbox=netbox_vm is not None,
                in_monitoring=zabbix_host is not None,
                cloud_provider=cloud_vm.provider if cloud_vm else None,
            )
            states.append(state)

        # Phase 2: IP-based fallback matching
        # For each state entry that is missing a system, try to find a match
        # from that system via shared IP address.
        for state in states:
            name_key = state.vm_name.lower()

            # Gather IPs from all sources that matched this entry by name
            state_ips: set[str] = set()
            if name_key in cloud_by_name:
                state_ips.update(cloud_by_name[name_key].ip_addresses)
            if name_key in netbox_by_name:
                state_ips.update(netbox_by_name[name_key].ip_addresses)
            if name_key in zabbix_by_name:
                state_ips.update(zabbix_by_name[name_key].ip_addresses)

            if not state_ips:
                continue

            # Try to find NetBox match by IP
            if not state.in_netbox:
                for ip in state_ips:
                    if ip in netbox_by_ip:
                        nb_vm = netbox_by_ip[ip]
                        nb_key = nb_vm.name.lower()
                        # Only match if that NetBox VM wasn't already name-matched
                        # to THIS entry, and hasn't been consumed by another IP match
                        if nb_key != name_key and nb_key not in ip_consumed_netbox:
                            state.in_netbox = True
                            ip_consumed_netbox.add(nb_key)
                            break

            # Try to find Zabbix match by IP
            if not state.in_monitoring:
                for ip in state_ips:
                    if ip in zabbix_by_ip:
                        zb_host = zabbix_by_ip[ip]
                        zb_key = zb_host.name.lower()
                        if zb_key != name_key and zb_key not in ip_consumed_zabbix:
                            state.in_monitoring = True
                            ip_consumed_zabbix.add(zb_key)
                            break

            # Try to find Cloud match by IP
            if not state.in_cloud:
                for ip in state_ips:
                    if ip in cloud_by_ip:
                        c_vm = cloud_by_ip[ip]
                        c_key = c_vm.name.lower()
                        if c_key != name_key and c_key not in ip_consumed_cloud:
                            state.in_cloud = True
                            state.cloud_provider = c_vm.provider
                            ip_consumed_cloud.add(c_key)
                            break

        # Phase 3: Compute discrepancies
        for state in states:
            state.discrepancies = self._compute_discrepancies(state)

        # Build summary
        summary = self._build_summary(states)

        return ComparisonResult(all_vms=states, summary=summary)

    def _compute_discrepancies(self, state: VMState) -> list[str]:
        """Determine discrepancy labels for a VM state."""
        discs: list[str] = []
        if state.in_cloud and not state.in_netbox:
            discs.append("in cloud but not in NetBox")
        if state.in_netbox and not state.in_cloud:
            discs.append("in NetBox but not in cloud")
        if state.in_cloud and not state.in_monitoring:
            discs.append("in cloud but not in monitoring")
        if state.in_monitoring and not state.in_cloud:
            discs.append("in monitoring but not in cloud")
        if state.in_netbox and not state.in_monitoring:
            discs.append("in NetBox but not in monitoring")
        return discs

    def _build_summary(self, states: list[VMState]) -> dict[str, int]:
        """Build summary counts from VM states."""
        total = len(states)
        in_sync = sum(1 for s in states if not s.discrepancies)
        with_issues = total - in_sync

        summary: dict[str, int] = {
            "total": total,
            "in_sync": in_sync,
            "with_discrepancies": with_issues,
            "in_cloud_only": sum(
                1 for s in states
                if s.in_cloud and not s.in_netbox and not s.in_monitoring
            ),
            "in_netbox_only": sum(
                1 for s in states
                if s.in_netbox and not s.in_cloud and not s.in_monitoring
            ),
            "in_monitoring_only": sum(
                1 for s in states
                if s.in_monitoring and not s.in_cloud and not s.in_netbox
            ),
        }
        return summary
