"""Comparison engine: cross-references cloud VMs, NetBox VMs, and Zabbix hosts."""

import logging

from infraverse.providers.base import VMInfo
from infraverse.providers.zabbix import ZabbixHost
from infraverse.comparison.models import ComparisonResult, VMState

logger = logging.getLogger(__name__)


class ComparisonEngine:
    """Compares VM presence across cloud providers, NetBox, and Zabbix."""

    def compare(
        self,
        cloud_vms: list[VMInfo],
        netbox_vms: list[VMInfo],
        zabbix_hosts: list[ZabbixHost] | None = None,
        monitoring_configured: bool = True,
        netbox_configured: bool = True,
        monitored_vm_names: set[str] | None = None,
    ) -> ComparisonResult:
        """Compare VMs across all three systems.

        Matching strategy:
        1. Primary: exact VM name match (case-insensitive)
        2. Secondary: shared IP address when names differ

        Args:
            cloud_vms: VMs from all cloud providers.
            netbox_vms: VMs from NetBox.
            zabbix_hosts: Hosts from Zabbix (legacy mode, used when
                monitored_vm_names is not provided).
            monitoring_configured: Whether monitoring (Zabbix) is configured.
                When False, monitoring-related discrepancies are not reported.
            netbox_configured: Whether NetBox data is available.
                When False, NetBox-related discrepancies are not reported.
            monitored_vm_names: Set of VM names (case-insensitive) known to be
                monitored (from MonitoringHost DB records). When provided,
                takes priority over zabbix_hosts for determining monitoring
                presence.

        Returns:
            ComparisonResult with per-VM state and summary.
        """
        # DB-driven monitoring: use pre-resolved monitored names
        if monitored_vm_names is not None:
            return self._compare_with_monitored_names(
                cloud_vms, netbox_vms, monitored_vm_names,
                monitoring_configured, netbox_configured,
            )

        # Legacy mode: full three-way matching with ZabbixHost list
        return self._compare_with_zabbix_hosts(
            cloud_vms, netbox_vms, zabbix_hosts or [],
            monitoring_configured, netbox_configured,
        )

    def _compare_with_monitored_names(
        self,
        cloud_vms: list[VMInfo],
        netbox_vms: list[VMInfo],
        monitored_vm_names: set[str],
        monitoring_configured: bool,
        netbox_configured: bool,
    ) -> ComparisonResult:
        """Compare using pre-resolved monitored VM names from DB.

        Monitoring presence is determined by name lookup in monitored_vm_names
        (case-insensitive). No IP-based monitoring matching is needed since
        the ingestion flow already resolved name/IP matches.
        """
        monitored_lower = {n.lower() for n in monitored_vm_names}

        cloud_by_name: dict[str, list[VMInfo]] = {}
        cloud_by_ip: dict[str, list[VMInfo]] = {}
        for vm in cloud_vms:
            cloud_by_name.setdefault(vm.name.lower(), []).append(vm)
            for ip in vm.ip_addresses:
                cloud_by_ip.setdefault(ip, []).append(vm)

        netbox_by_name: dict[str, list[VMInfo]] = {}
        netbox_by_ip: dict[str, list[VMInfo]] = {}
        for vm in netbox_vms:
            netbox_by_name.setdefault(vm.name.lower(), []).append(vm)
            for ip in vm.ip_addresses:
                netbox_by_ip.setdefault(ip, []).append(vm)

        # Only cloud and netbox names participate (monitoring is a lookup)
        all_names: set[str] = set()
        all_names.update(cloud_by_name.keys())
        all_names.update(netbox_by_name.keys())

        ip_merged_names: set[str] = set()
        states: list[VMState] = []

        for name in sorted(all_names):
            cloud_vms_for_name = cloud_by_name.get(name, [])
            netbox_vms_for_name = netbox_by_name.get(name, [])

            has_netbox = len(netbox_vms_for_name) > 0
            has_monitoring = name in monitored_lower

            if len(cloud_vms_for_name) <= 1:
                cloud_vm = cloud_vms_for_name[0] if cloud_vms_for_name else None
                display_name = name
                if cloud_vm:
                    display_name = cloud_vm.name
                elif netbox_vms_for_name:
                    display_name = netbox_vms_for_name[0].name

                state = VMState(
                    vm_name=display_name,
                    in_cloud=cloud_vm is not None,
                    in_netbox=has_netbox,
                    in_monitoring=has_monitoring,
                    cloud_provider=cloud_vm.provider if cloud_vm else None,
                )
                states.append(state)
            else:
                for cloud_vm in cloud_vms_for_name:
                    state = VMState(
                        vm_name=cloud_vm.name,
                        in_cloud=True,
                        in_netbox=has_netbox,
                        in_monitoring=has_monitoring,
                        cloud_provider=cloud_vm.provider,
                    )
                    states.append(state)

        # IP-based fallback for cloud <-> netbox matching only
        for state in states:
            name_key = state.vm_name.lower()
            if name_key in ip_merged_names:
                continue

            state_ips: set[str] = set()
            for cvm in cloud_by_name.get(name_key, []):
                state_ips.update(cvm.ip_addresses)
            for nb_vm in netbox_by_name.get(name_key, []):
                state_ips.update(nb_vm.ip_addresses)

            if not state_ips:
                continue

            if not state.in_netbox:
                matched = False
                for ip in state_ips:
                    if matched:
                        break
                    for nb_vm in netbox_by_ip.get(ip, []):
                        nb_key = nb_vm.name.lower()
                        if nb_key != name_key and nb_key not in ip_merged_names:
                            state.in_netbox = True
                            ip_merged_names.add(nb_key)
                            matched = True
                            break

            if not state.in_cloud:
                matched = False
                for ip in state_ips:
                    if matched:
                        break
                    for c_vm in cloud_by_ip.get(ip, []):
                        c_key = c_vm.name.lower()
                        if c_key != name_key and c_key not in ip_merged_names:
                            state.in_cloud = True
                            state.cloud_provider = c_vm.provider
                            ip_merged_names.add(c_key)
                            matched = True
                            break

        states = [
            s for s in states if s.vm_name.lower() not in ip_merged_names
        ]

        for state in states:
            state.discrepancies = self._compute_discrepancies(
                state,
                monitoring_configured=monitoring_configured,
                netbox_configured=netbox_configured,
            )

        summary = self.build_summary(states)
        return ComparisonResult(all_vms=states, summary=summary)

    def _compare_with_zabbix_hosts(
        self,
        cloud_vms: list[VMInfo],
        netbox_vms: list[VMInfo],
        zabbix_hosts: list[ZabbixHost],
        monitoring_configured: bool,
        netbox_configured: bool,
    ) -> ComparisonResult:
        """Legacy comparison with raw ZabbixHost list."""
        # Build lookup structures (name lowercased -> source data)
        # Cloud uses list values to handle same-named VMs from different providers
        cloud_by_name: dict[str, list[VMInfo]] = {}
        cloud_by_ip: dict[str, list[VMInfo]] = {}
        for vm in cloud_vms:
            cloud_by_name.setdefault(vm.name.lower(), []).append(vm)
            for ip in vm.ip_addresses:
                cloud_by_ip.setdefault(ip, []).append(vm)

        netbox_by_name: dict[str, list[VMInfo]] = {}
        netbox_by_ip: dict[str, list[VMInfo]] = {}
        for vm in netbox_vms:
            netbox_by_name.setdefault(vm.name.lower(), []).append(vm)
            for ip in vm.ip_addresses:
                netbox_by_ip.setdefault(ip, []).append(vm)

        zabbix_by_name: dict[str, list[ZabbixHost]] = {}
        zabbix_by_ip: dict[str, list[ZabbixHost]] = {}
        for host in zabbix_hosts:
            zabbix_by_name.setdefault(host.name.lower(), []).append(host)
            for ip in host.ip_addresses:
                zabbix_by_ip.setdefault(ip, []).append(host)

        # Collect all unique VM names (case-insensitive)
        all_names: set[str] = set()
        all_names.update(cloud_by_name.keys())
        all_names.update(netbox_by_name.keys())
        all_names.update(zabbix_by_name.keys())

        # Names whose standalone VMState entries should be removed after IP matching
        # because they were merged into another entry via IP
        ip_merged_names: set[str] = set()

        states: list[VMState] = []

        # Phase 1: Name-based matching
        for name in sorted(all_names):
            cloud_vms_for_name = cloud_by_name.get(name, [])
            netbox_vms_for_name = netbox_by_name.get(name, [])
            zabbix_hosts_for_name = zabbix_by_name.get(name, [])

            has_netbox = len(netbox_vms_for_name) > 0
            has_zabbix = len(zabbix_hosts_for_name) > 0

            if len(cloud_vms_for_name) <= 1:
                # Normal case: zero or one cloud VM with this name
                cloud_vm = cloud_vms_for_name[0] if cloud_vms_for_name else None

                display_name = name
                if cloud_vm:
                    display_name = cloud_vm.name
                elif netbox_vms_for_name:
                    display_name = netbox_vms_for_name[0].name
                elif zabbix_hosts_for_name:
                    display_name = zabbix_hosts_for_name[0].name

                state = VMState(
                    vm_name=display_name,
                    in_cloud=cloud_vm is not None,
                    in_netbox=has_netbox,
                    in_monitoring=has_zabbix,
                    cloud_provider=cloud_vm.provider if cloud_vm else None,
                )
                states.append(state)
            else:
                # Multiple cloud VMs with same name from different providers
                for cloud_vm in cloud_vms_for_name:
                    state = VMState(
                        vm_name=cloud_vm.name,
                        in_cloud=True,
                        in_netbox=has_netbox,
                        in_monitoring=has_zabbix,
                        cloud_provider=cloud_vm.provider,
                    )
                    states.append(state)

        # Phase 2: IP-based fallback matching
        # For each state entry that is missing a system, try to find a match
        # from that system via shared IP address. Matched counterparts are
        # tracked in ip_merged_names and removed afterwards to avoid duplicates.
        for state in states:
            name_key = state.vm_name.lower()

            if name_key in ip_merged_names:
                continue

            # Gather IPs from all sources that matched this entry by name
            state_ips: set[str] = set()
            for cvm in cloud_by_name.get(name_key, []):
                state_ips.update(cvm.ip_addresses)
            for nb_vm in netbox_by_name.get(name_key, []):
                state_ips.update(nb_vm.ip_addresses)
            for zb_host in zabbix_by_name.get(name_key, []):
                state_ips.update(zb_host.ip_addresses)

            if not state_ips:
                continue

            # Try to find NetBox match by IP
            if not state.in_netbox:
                matched = False
                for ip in state_ips:
                    if matched:
                        break
                    for nb_vm in netbox_by_ip.get(ip, []):
                        nb_key = nb_vm.name.lower()
                        if nb_key != name_key and nb_key not in ip_merged_names:
                            state.in_netbox = True
                            ip_merged_names.add(nb_key)
                            matched = True
                            break

            # Try to find Zabbix match by IP
            if not state.in_monitoring:
                matched = False
                for ip in state_ips:
                    if matched:
                        break
                    for zb_host in zabbix_by_ip.get(ip, []):
                        zb_key = zb_host.name.lower()
                        if zb_key != name_key and zb_key not in ip_merged_names:
                            state.in_monitoring = True
                            ip_merged_names.add(zb_key)
                            matched = True
                            break

            # Try to find Cloud match by IP
            if not state.in_cloud:
                matched = False
                for ip in state_ips:
                    if matched:
                        break
                    for c_vm in cloud_by_ip.get(ip, []):
                        c_key = c_vm.name.lower()
                        if c_key != name_key and c_key not in ip_merged_names:
                            state.in_cloud = True
                            state.cloud_provider = c_vm.provider
                            ip_merged_names.add(c_key)
                            matched = True
                            break

        # Remove entries that were merged into other entries via IP matching
        states = [
            s for s in states if s.vm_name.lower() not in ip_merged_names
        ]

        # Phase 3: Compute discrepancies
        for state in states:
            state.discrepancies = self._compute_discrepancies(
                state,
                monitoring_configured=monitoring_configured,
                netbox_configured=netbox_configured,
            )

        # Build summary
        summary = self.build_summary(states)

        return ComparisonResult(all_vms=states, summary=summary)

    def _compute_discrepancies(
        self,
        state: VMState,
        monitoring_configured: bool = True,
        netbox_configured: bool = True,
    ) -> list[str]:
        """Determine discrepancy labels for a VM state."""
        discs: list[str] = []
        if netbox_configured:
            if state.in_cloud and not state.in_netbox:
                discs.append("in cloud but not in NetBox")
            if state.in_netbox and not state.in_cloud:
                discs.append("in NetBox but not in cloud")
        if monitoring_configured:
            if state.in_cloud and not state.in_monitoring:
                discs.append("in cloud but not in monitoring")
            if state.in_monitoring and not state.in_cloud:
                discs.append("in monitoring but not in cloud")
            if netbox_configured and state.in_netbox and not state.in_monitoring:
                discs.append("in NetBox but not in monitoring")
            if netbox_configured and state.in_monitoring and not state.in_netbox:
                discs.append("in monitoring but not in NetBox")
        return discs

    def build_summary(self, states: list[VMState]) -> dict[str, int]:
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
            "missing_from_netbox": sum(
                1 for s in states if s.in_cloud and not s.in_netbox
            ),
            "missing_from_cloud": sum(
                1 for s in states if s.in_netbox and not s.in_cloud
            ),
            "missing_from_monitoring": sum(
                1 for s in states if s.in_cloud and not s.in_monitoring
            ),
        }
        return summary
