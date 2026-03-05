"""Base abstractions for cloud providers."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class VMInfo:
    """Normalized VM representation from any cloud provider."""

    name: str
    id: str
    status: str  # "active" | "offline" | "unknown"
    ip_addresses: list[str] = field(default_factory=list)
    vcpus: int = 0
    memory_mb: int = 0
    provider: str = ""
    cloud_name: str = ""
    folder_name: str = ""


@runtime_checkable
class CloudProvider(Protocol):
    """Interface that all cloud provider clients must implement."""

    def fetch_vms(self) -> list[VMInfo]: ...

    def get_provider_name(self) -> str: ...
