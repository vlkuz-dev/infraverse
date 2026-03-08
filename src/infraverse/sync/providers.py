"""Build cloud provider clients from CloudAccount credentials."""

import logging
from typing import Any, List, Tuple

from infraverse.sync.provider_profile import ProviderProfile, get_profile

logger = logging.getLogger(__name__)

# Type alias — any cloud client (YandexCloudClient, VCloudDirectorClient, etc.)
CloudClient = Any


def build_provider(account) -> Tuple[CloudClient, ProviderProfile]:
    """Build a (cloud_client, ProviderProfile) tuple from a CloudAccount.

    Args:
        account: CloudAccount DB model with .provider_type and .config dict.

    Returns:
        Tuple of (client, profile).

    Raises:
        ValueError: If provider_type is unknown.
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
        raise ValueError(f"Unknown provider type: {account.provider_type}")


def build_providers_from_accounts(accounts) -> List[Tuple[CloudClient, ProviderProfile]]:
    """Build provider list from a sequence of CloudAccount objects.

    Skips inactive accounts and accounts with unknown provider types.

    Args:
        accounts: Iterable of CloudAccount DB model objects.

    Returns:
        List of (client, profile) tuples ready for SyncEngine.
    """
    providers = []
    for account in accounts:
        if hasattr(account, "is_active") and not account.is_active:
            logger.debug("Skipping inactive account: %s", account.name)
            continue
        try:
            providers.append(build_provider(account))
        except ValueError:
            logger.warning(
                "Unknown provider type '%s' for account %s, skipping",
                account.provider_type, account.name,
            )
        except Exception:
            logger.exception("Failed to build provider for account %s", account.name)
    return providers
