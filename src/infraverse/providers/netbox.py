"""
NetBox client for managing virtualization resources.
Maps Yandex Cloud structure to NetBox:
- Sites = Availability Zones
- Cluster Type = yandex-cloud
- Clusters = Folders
"""

import logging
from typing import Dict, Optional

import pynetbox

from infraverse.providers.netbox_infrastructure import NetBoxInfrastructureMixin
from infraverse.providers.netbox_interfaces import NetBoxInterfacesMixin
from infraverse.providers.netbox_prefixes import NetBoxPrefixesMixin
from infraverse.providers.netbox_tags import NetBoxTagsMixin
from infraverse.providers.netbox_vms import NetBoxVMsMixin

logger = logging.getLogger(__name__)


class NetBoxClient(
    NetBoxVMsMixin,
    NetBoxInterfacesMixin,
    NetBoxPrefixesMixin,
    NetBoxInfrastructureMixin,
    NetBoxTagsMixin,
):
    """NetBox API client for VM synchronization with Yandex Cloud mapping."""

    def __init__(
        self,
        url: str,
        token: str,
        dry_run: bool = False
    ):
        """
        Initialize NetBox client.

        Args:
            url: NetBox API URL
            token: NetBox API token
            dry_run: If True, don't make actual changes
        """
        self.nb = pynetbox.api(url, token=token)
        self.dry_run = dry_run
        self._cluster_type_cache: Dict[str, int] = {}
        self._cluster_type_id: Optional[int] = None  # backward compat shortcut
        self._tenant_cache: Dict[str, int] = {}

        logger.info(f"Initialized NetBox client for {url} (dry_run={dry_run})")
        self._sync_tag_cache: Dict[str, int] = {}
        self._sync_tag_id: Optional[int] = None  # backward compat shortcut
