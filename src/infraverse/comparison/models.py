"""Data models for infrastructure comparison results."""

from dataclasses import dataclass, field


@dataclass
class VMState:
    """State of a single VM across all three systems."""

    vm_name: str
    in_cloud: bool = False
    in_netbox: bool = False
    in_monitoring: bool = False
    cloud_provider: str | None = None
    discrepancies: list[str] = field(default_factory=list)
    sync_reasons: dict[str, str] = field(default_factory=dict)
    is_monitoring_exempt: bool = False
    monitoring_exempt_reason: str | None = None


@dataclass
class ComparisonResult:
    """Aggregated comparison result across all systems."""

    all_vms: list[VMState] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
