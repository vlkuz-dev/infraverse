"""Platform detection — map OS names to NetBox platform slugs."""

import logging
import re

from infraverse.providers.netbox import NetBoxClient

logger = logging.getLogger(__name__)

# Default platform slug for unrecognized operating systems
DEFAULT_PLATFORM_SLUG = "linux"


def detect_platform_slug(os_name: str) -> str:
    """Detect platform slug from OS name string. Returns a slug suitable for NetBox platform lookup."""
    if not os_name:
        return DEFAULT_PLATFORM_SLUG

    os_name_lower = os_name.lower()

    if "windows" in os_name_lower:
        if "2019" in os_name_lower:
            return "windows-2019"
        elif "2022" in os_name_lower:
            return "windows-2022"
        elif "2025" in os_name_lower:
            return "windows-2025"
        else:
            return "windows"
    elif "ubuntu" in os_name_lower:
        if "22.04" in os_name_lower or "22-04" in os_name_lower or "jammy" in os_name_lower:
            return "ubuntu-22-04"
        elif "24.04" in os_name_lower or "24-04" in os_name_lower or "noble" in os_name_lower:
            return "ubuntu-24-04"
        else:
            return "ubuntu-22-04"
    elif "debian" in os_name_lower:
        if re.search(r'\b12\b', os_name_lower) or "bookworm" in os_name_lower:
            return "debian-12"
        elif re.search(r'\b11\b', os_name_lower) or "bullseye" in os_name_lower:
            return "debian-11"
        else:
            return "debian-12"
    elif "centos" in os_name_lower:
        if re.search(r'\b7\b', os_name_lower):
            return "centos-7"
        else:
            return DEFAULT_PLATFORM_SLUG
    elif "alma" in os_name_lower or "almalinux" in os_name_lower:
        if re.search(r'\b9\b', os_name_lower):
            return "almalinux-9"
        else:
            return DEFAULT_PLATFORM_SLUG
    elif "oracle" in os_name_lower:
        if re.search(r'\b9\b', os_name_lower):
            return "oracle-linux-9"
        else:
            return DEFAULT_PLATFORM_SLUG
    elif any(k in os_name_lower for k in ("rocky", "rhel", "red hat", "fedora")):
        return DEFAULT_PLATFORM_SLUG
    elif "linux" in os_name_lower:
        return DEFAULT_PLATFORM_SLUG

    return DEFAULT_PLATFORM_SLUG


def detect_platform_id(os_name: str, netbox: NetBoxClient = None) -> int:
    """Detect NetBox platform ID from OS name string.

    If a NetBox client is provided, resolves the platform by slug at runtime.
    Otherwise returns 0 (caller must handle).
    """
    slug = detect_platform_slug(os_name)
    if netbox:
        return netbox.ensure_platform(slug)
    return 0
