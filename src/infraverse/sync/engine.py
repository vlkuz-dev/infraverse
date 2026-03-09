"""Top-level sync engine that orchestrates the full sync cycle."""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from infraverse.providers.netbox import NetBoxClient
from infraverse.sync.infrastructure import sync_infrastructure
from infraverse.sync.vms import sync_vms
from infraverse.sync.batch import sync_vms_optimized
from infraverse.sync.provider_profile import ProviderProfile

logger = logging.getLogger(__name__)

# Type alias for a cloud provider client (YandexCloudClient, VCloudDirectorClient, etc.)
CloudClient = Any

# Provider tuple: (client, profile), (client, profile, tenant_name),
# or (client, profile, tenant_name, tenant_description)
ProviderTuple = Union[
    Tuple[CloudClient, ProviderProfile],
    Tuple[CloudClient, ProviderProfile, Optional[str]],
    Tuple[CloudClient, ProviderProfile, Optional[str], Optional[str]],
]


class SyncEngine:
    """Orchestrates the full Cloud -> NetBox sync cycle for all configured providers."""

    def __init__(
        self,
        netbox: NetBoxClient,
        providers: List[ProviderTuple],
        dry_run: bool = False,
    ):
        self.nb = netbox
        self._providers = providers
        self.dry_run = dry_run

    def run(self, use_batch: bool = True, cleanup: bool = True) -> Dict[str, Any]:
        """Execute full sync cycle for all configured providers.

        Args:
            use_batch: Use optimized batch sync (True) or standard sequential (False).
            cleanup: Whether to clean up orphaned objects.

        Returns:
            Summary statistics keyed by provider key.
        """
        logger.info("Starting Cloud to NetBox sync...")
        logger.info("Dry run mode: %s", self.dry_run)
        logger.info(
            "Providers configured: %s",
            [p[1].display_name for p in self._providers],
        )

        all_stats: Dict[str, Any] = {}

        for provider_tuple in self._providers:
            client = provider_tuple[0]
            profile = provider_tuple[1]
            tenant_name = provider_tuple[2] if len(provider_tuple) > 2 else None
            tenant_description = provider_tuple[3] if len(provider_tuple) > 3 else None
            logger.info("Syncing provider: %s", profile.display_name)
            try:
                provider_stats = self._sync_provider(
                    client, profile, use_batch, cleanup,
                    tenant_name=tenant_name, tenant_description=tenant_description,
                )
                all_stats[profile.key] = provider_stats
            except Exception:
                logger.exception("Sync failed for provider %s", profile.display_name)
                all_stats[profile.key] = {"error": "sync failed"}

        logger.info("Synchronization completed!")
        return all_stats

    def _sync_provider(
        self, client, profile, use_batch, cleanup,
        tenant_name=None, tenant_description=None,
    ) -> Dict[str, Any]:
        """Sync a single provider to NetBox."""
        data = client.fetch_all_data()
        if not data or not isinstance(data, dict):
            raise RuntimeError(f"Failed to fetch data from {profile.display_name}")

        do_cleanup = cleanup
        if cleanup and data.get("_has_fetch_errors"):
            logger.warning(
                "Skipping orphan cleanup for %s because some API calls failed",
                profile.display_name,
            )
            do_cleanup = False

        # Ensure sync tag exists early
        self.nb.ensure_sync_tag(
            tag_name=profile.tag_name,
            tag_slug=profile.tag_slug,
            tag_color=profile.tag_color,
            tag_description=profile.tag_description,
        )

        # Pre-cache tenant with description so downstream calls use cached ID
        if tenant_name:
            self.nb.ensure_tenant(
                name=tenant_name, description=tenant_description,
            )

        # Sync infrastructure and get ID mappings
        id_mapping = sync_infrastructure(
            data, self.nb, cleanup_orphaned=do_cleanup, provider_profile=profile,
        )

        # Sync VMs
        if use_batch:
            logger.info("Using optimized sync with batch operations...")
            stats = sync_vms_optimized(
                data, self.nb, id_mapping,
                cleanup_orphaned=do_cleanup,
                provider_profile=profile,
                tenant_name=tenant_name,
            )
        else:
            logger.info("Using standard sync (sequential operations)...")
            stats = sync_vms(
                data, self.nb, id_mapping,
                cleanup_orphaned=do_cleanup,
                provider_profile=profile,
                tenant_name=tenant_name,
            )

        return stats
