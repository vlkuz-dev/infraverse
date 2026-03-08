"""Monitoring exclusion rules for VMs that don't need monitoring checks."""

import fnmatch

from infraverse.config_file import MonitoringExclusionRule


def check_monitoring_exclusion(
    vm_name: str,
    vm_status: str,
    rules: list[MonitoringExclusionRule],
) -> tuple[bool, str | None]:
    """Check if a VM is exempt from monitoring.

    Returns:
        Tuple of (is_exempt, reason). First matching rule wins.
    """
    for rule in rules:
        name_matches = True
        status_matches = True

        if rule.name_pattern is not None:
            name_matches = fnmatch.fnmatch(vm_name.lower(), rule.name_pattern.lower())

        if rule.status is not None:
            status_matches = vm_status.lower() == rule.status.lower()

        if name_matches and status_matches:
            return True, rule.reason

    return False, None
