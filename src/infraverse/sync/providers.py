"""Build cloud provider clients from CloudAccount credentials."""

import logging
from typing import Any, List, Optional, Tuple

from infraverse.sync.provider_profile import ProviderProfile, get_profile

logger = logging.getLogger(__name__)

# Type alias — any cloud client (YandexCloudClient, VCloudDirectorClient, etc.)
CloudClient = Any


def build_provider(account) -> Optional[Tuple[CloudClient, ProviderProfile]]:
    """Build a (cloud_client, ProviderProfile) tuple from a CloudAccount.

    Args:
        account: CloudAccount DB model with .provider_type and .config dict.

    Returns:
        Tuple of (client, profile), or None if provider_type is unknown.
    """
    creds = account.config or {}

    if account.provider_type == "yandex_cloud":
        from infraverse.providers.yandex import YandexCloudClient
        from infraverse.providers.yc_auth import resolve_token_provider

        client = YandexCloudClient(token_provider=resolve_token_provider(creds))
        return (client, get_profile("yandex_cloud"))

    elif account.provider_type == "vcloud":
        from infraverse.providers.vcloud import VCloudDirectorClient

        client = VCloudDirectorClient(
            url=creds.get("url", ""),
            username=creds.get("username", ""),
            password=creds.get("password", ""),
            org=creds.get("org", "System"),
        )
        return (client, get_profile("vcloud"))

    else:
        logger.warning(
            "Unknown provider type '%s' for account %s",
            account.provider_type, getattr(account, "name", "unknown"),
        )
        return None


def build_zabbix_client(infraverse_config=None, legacy_config=None):
    """Build a ZabbixClient if monitoring is configured, otherwise return None.

    Checks infraverse_config.monitoring first (config-file mode).
    If infraverse_config is set but has no monitoring section, returns None
    without falling back to legacy_config (env-var mode).

    Args:
        infraverse_config: InfraverseConfig from YAML config file.
        legacy_config: Legacy Config from environment variables.

    Returns:
        ZabbixClient instance, or None if not configured or on error.
    """
    # Config-file mode: use InfraverseConfig monitoring section
    if infraverse_config is not None:
        if not getattr(infraverse_config, "monitoring_configured", False):
            return None
        try:
            from infraverse.providers.zabbix import ZabbixClient

            monitoring = infraverse_config.monitoring
            return ZabbixClient(
                url=monitoring.zabbix_url,
                username=monitoring.zabbix_username,
                password=monitoring.zabbix_password,
            )
        except Exception as exc:
            logger.error("Failed to build Zabbix client: %s", exc)
            return None

    # Env-var mode fallback
    if legacy_config is not None and getattr(legacy_config, "zabbix_configured", False):
        try:
            from infraverse.providers.zabbix import ZabbixClient

            return ZabbixClient(
                url=legacy_config.zabbix_url,
                username=legacy_config.zabbix_user,
                password=legacy_config.zabbix_password,
            )
        except Exception as exc:
            logger.error("Failed to build Zabbix client: %s", exc)
            return None

    return None


def build_providers_from_accounts(
    accounts,
) -> List[Tuple[CloudClient, ProviderProfile, Optional[str], Optional[str]]]:
    """Build provider list from a sequence of CloudAccount objects.

    Skips inactive accounts and accounts with unknown provider types.

    Args:
        accounts: Iterable of CloudAccount DB model objects.
            If accounts have a .tenant relation loaded, tenant_name and
            tenant_description are extracted.

    Returns:
        List of (client, profile, tenant_name, tenant_description) tuples
        ready for SyncEngine.
    """
    providers = []
    for account in accounts:
        if hasattr(account, "is_active") and not account.is_active:
            logger.debug("Skipping inactive account: %s", account.name)
            continue
        try:
            result = build_provider(account)
            if result is not None:
                client, profile = result
                tenant = getattr(account, "tenant", None)
                tenant_name = tenant.name if tenant is not None else None
                tenant_description = getattr(tenant, "description", None) if tenant is not None else None
                providers.append((client, profile, tenant_name, tenant_description))
        except Exception:
            logger.exception("Failed to build provider for account %s", account.name)
    return providers
