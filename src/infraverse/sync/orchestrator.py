"""Shared orchestration for ingestion cycles (CLI + Scheduler)."""

import logging

from infraverse.db.repository import Repository
from infraverse.sync.config_sync import sync_config_to_db
from infraverse.sync.ingest import DataIngestor
from infraverse.sync.providers import build_provider, build_zabbix_client

logger = logging.getLogger(__name__)


def _build_providers_for_ingestion(accounts, infraverse_config=None, legacy_config=None):
    """Build provider dict mapping account_id -> client for ingestion.

    In config-file mode (infraverse_config set), reads credentials from
    account.config via build_provider().
    In env-var mode (legacy_config set), reads credentials from the legacy
    Config object.
    """
    providers = {}
    for account in accounts:
        try:
            if infraverse_config is not None:
                result = build_provider(account)
                if result is not None:
                    providers[account.id] = result[0]
            elif legacy_config is not None:
                client = _build_legacy_provider(account, legacy_config)
                if client is not None:
                    providers[account.id] = client
        except Exception as exc:
            logger.error(
                "Failed to build provider for account %s: %s",
                account.name, exc,
            )
    return providers


def _build_legacy_provider(account, config):
    """Build a cloud client from env-var-based Config for the given account."""
    if account.provider_type == "yandex_cloud":
        from infraverse.providers.yandex import YandexCloudClient
        from infraverse.providers.yc_auth import resolve_token_provider

        yc_creds = {}
        if getattr(config, "yc_sa_key_file", None):
            yc_creds["sa_key_file"] = config.yc_sa_key_file
        else:
            yc_creds["token"] = config.yc_token
        return YandexCloudClient(token_provider=resolve_token_provider(yc_creds))

    elif account.provider_type == "vcloud" and getattr(config, "vcd_configured", False):
        from infraverse.providers.vcloud import VCloudDirectorClient

        return VCloudDirectorClient(
            url=config.vcd_url,
            username=config.vcd_user,
            password=config.vcd_password,
            org=(account.config or {}).get(
                "org", getattr(config, "vcd_org", None) or "System",
            ),
        )

    return None


def run_ingestion_cycle(session, infraverse_config=None, legacy_config=None) -> dict:
    """Run a full ingestion cycle: sync config, build providers, ingest data.

    Handles both config-file mode (infraverse_config) and env-var mode
    (legacy_config).

    Args:
        session: SQLAlchemy session (caller manages lifecycle).
        infraverse_config: InfraverseConfig from YAML config file.
        legacy_config: Legacy Config from environment variables.

    Returns:
        Dict with ingestion results from DataIngestor.ingest_all().
    """
    # Sync config to DB if YAML config is provided
    if infraverse_config is not None:
        sync_config_to_db(infraverse_config, session)
        session.commit()

    # Load accounts
    repo = Repository(session)
    accounts = repo.list_cloud_accounts()

    # Filter to active accounts only when using config-file mode
    if infraverse_config is not None:
        accounts = [a for a in accounts if a.is_active]

    # Build providers
    providers = _build_providers_for_ingestion(
        accounts, infraverse_config=infraverse_config, legacy_config=legacy_config,
    )

    # Build Zabbix client
    zabbix_client = build_zabbix_client(
        infraverse_config=infraverse_config, legacy_config=legacy_config,
    )

    # Run ingestion
    exclusion_rules = []
    if infraverse_config is not None:
        exclusion_rules = infraverse_config.monitoring_exclusions

    ingestor = DataIngestor(session, exclusion_rules=exclusion_rules)
    results = ingestor.ingest_all(providers, zabbix_client)

    return results
