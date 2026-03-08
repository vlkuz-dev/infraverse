"""Size conversion utilities for cloud VM resources.

Centralizes byte/MB/GiB conversion logic used across sync modules.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

BYTES_PER_GIB = 1024 ** 3
NETBOX_MB_PER_GIB = 1000  # NetBox uses decimal MB display for GiB values


def parse_disk_size_mb(size_bytes: int | float | str) -> int:
    """Convert disk size in bytes to NetBox MB value.

    NetBox displays GiB as *1000 MB (decimal), so 10 GiB disk = 10000 MB.
    Handles string, int, and float input types.
    """
    return round(int(size_bytes) / BYTES_PER_GIB * NETBOX_MB_PER_GIB)


def parse_memory_mb(resources: Dict[str, Any], vm_name: str = "unknown") -> int:
    """Parse memory from YC resources dict, handling string/int/float types.

    Returns MB value suitable for NetBox (which displays GB = MB / 1000).
    YC returns bytes in binary units (GiB), so we convert: bytes -> GiB -> * 1000 -> MB.
    """
    memory = resources.get("memory", 0)
    memory_mb = 0
    if memory:
        try:
            if isinstance(memory, str):
                memory_clean = ''.join(filter(str.isdigit, memory))
                if memory_clean:
                    memory_int = int(memory_clean)
                    if memory_int < 1000:
                        # Value in GB — convert to NetBox MB
                        memory_mb = memory_int * NETBOX_MB_PER_GIB
                    elif memory_int < 1000000:
                        memory_mb = memory_int
                    else:
                        # Value in bytes — convert to GiB then to NetBox MB
                        memory_mb = round(memory_int / BYTES_PER_GIB * NETBOX_MB_PER_GIB)
                else:
                    logger.warning(f"VM {vm_name}: could not parse memory string '{memory}'")
            elif isinstance(memory, (int, float)):
                memory_int = int(memory)
                if memory_int < 1000:
                    # Value in GB — convert to NetBox MB
                    memory_mb = memory_int * NETBOX_MB_PER_GIB
                elif memory_int < 1000000:
                    memory_mb = memory_int
                else:
                    # Value in bytes — convert to GiB then to NetBox MB
                    memory_mb = round(memory_int / BYTES_PER_GIB * NETBOX_MB_PER_GIB)
            else:
                logger.warning(f"VM {vm_name}: unexpected memory type {type(memory).__name__}: {memory}")
        except (ValueError, TypeError) as e:
            logger.error(f"VM {vm_name}: failed to parse memory value {memory}: {e}")
            memory_mb = 0
    return memory_mb


def parse_cores(resources: Dict[str, Any], vm_name: str = "unknown") -> int:
    """Parse cores from YC resources dict, handling string/int/float types."""
    cores = resources.get("cores", 1)
    vcpus = 1
    if cores:
        try:
            if isinstance(cores, str):
                cores_clean = ''.join(filter(str.isdigit, cores))
                if cores_clean:
                    vcpus = int(cores_clean)
                else:
                    logger.warning(f"VM {vm_name}: could not parse cores string '{cores}'")
            elif isinstance(cores, (int, float)):
                vcpus = int(cores)
            else:
                logger.warning(f"VM {vm_name}: unexpected cores type {type(cores).__name__}: {cores}")
        except (ValueError, TypeError) as e:
            logger.error(f"VM {vm_name}: failed to parse cores value {cores}: {e}")
            vcpus = 1
    return vcpus
