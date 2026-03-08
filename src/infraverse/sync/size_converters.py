"""Size conversion utilities for cloud VM resources.

Centralizes byte/MB/GiB conversion logic used across sync modules.
"""

BYTES_PER_GIB = 1024 ** 3
NETBOX_MB_PER_GIB = 1000  # NetBox uses decimal MB display for GiB values


def parse_disk_size_mb(size_bytes: int | float | str) -> int:
    """Convert disk size in bytes to NetBox MB value.

    NetBox displays GiB as *1000 MB (decimal), so 10 GiB disk = 10000 MB.
    Handles string, int, and float input types.
    """
    return round(int(size_bytes) / BYTES_PER_GIB * NETBOX_MB_PER_GIB)
