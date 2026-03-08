"""Top-level sync engine that orchestrates the full sync cycle."""

import logging
from typing import Any, Dict

from infraverse.config import Config
from infraverse.providers.yandex import YandexCloudClient
from infraverse.providers.netbox import NetBoxClient
from infraverse.sync.infrastructure import sync_infrastructure
from infraverse.sync.vms import sync_vms
from infraverse.sync.batch import sync_vms_optimized
from infraverse.sync.provider_profile import YC_PROFILE, VCLOUD_PROFILE

logger = logging.getLogger(__name__)


class SyncEngine:
    """Orchestrates the full Cloud -> NetBox sync cycle for all configured providers."""

    def __init__(self, config: Config):
        self.config = config
        self.nb = NetBoxClient(
            url=config.netbox_url,
            token=config.netbox_token,
            dry_run=config.dry_run,
        )
        self._providers = []  # list of (client, ProviderProfile)

        # Always add YC
        from infraverse.providers.yc_auth import resolve_token_provider

        yc_creds: dict = {}
        if config.yc_sa_key_file:
            yc_creds["sa_key_file"] = config.yc_sa_key_file
        else:
            yc_creds["token"] = config.yc_token
        yc_client = YandexCloudClient(token_provider=resolve_token_provider(yc_creds))
        self._providers.append((yc_client, YC_PROFILE))

        # Add vCloud if configured
        if config.vcd_configured:
            from infraverse.providers.vcloud import VCloudDirectorClient

            vcd_client = VCloudDirectorClient(
                url=config.vcd_url,
                username=config.vcd_user,
                password=config.vcd_password,
                org=config.vcd_org or "System",
            )
            self._providers.append((vcd_client, VCLOUD_PROFILE))

    def run(self, use_batch: bool = True, cleanup: bool = True) -> Dict[str, Any]:
        """Execute full sync cycle for all configured providers.

        Args:
            use_batch: Use optimized batch sync (True) or standard sequential (False).
            cleanup: Whether to clean up orphaned objects.

        Returns:
            Summary statistics keyed by provider key.
        """
        logger.info("Starting Cloud to NetBox sync...")
        logger.info("Dry run mode: %s", self.config.dry_run)
        logger.info("Providers configured: %s", [p.display_name for _, p in self._providers])

        all_stats: Dict[str, Any] = {}

        for client, profile in self._providers:
            logger.info("Syncing provider: %s", profile.display_name)
            try:
                provider_stats = self._sync_provider(client, profile, use_batch, cleanup)
                all_stats[profile.key] = provider_stats
            except Exception:
                logger.exception("Sync failed for provider %s", profile.display_name)
                all_stats[profile.key] = {"error": "sync failed"}

        logger.info("Synchronization completed!")
        return all_stats

    def _sync_provider(self, client, profile, use_batch, cleanup) -> Dict[str, Any]:
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
            )
        else:
            logger.info("Using standard sync (sequential operations)...")
            stats = sync_vms(
                data, self.nb, id_mapping,
                cleanup_orphaned=do_cleanup,
                provider_profile=profile,
            )

        return stats
