"""Synchronize YAML config file contents to database records."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from infraverse.config_file import InfraverseConfig
from infraverse.db.repository import Repository


@dataclass
class SyncReport:
    tenants_created: int = 0
    tenants_updated: int = 0
    accounts_created: int = 0
    accounts_updated: int = 0
    accounts_deactivated: int = 0


def sync_config_to_db(config: InfraverseConfig, session: Session) -> SyncReport:
    """Synchronize config tenants and cloud accounts to the database.

    - Creates new tenants/accounts that exist in config but not in DB.
    - Updates existing tenants/accounts with current config values.
    - Deactivates accounts in DB that are no longer in config (sets is_active=False).
    - Does NOT delete any data.

    Returns a SyncReport with counts of changes made.
    """
    repo = Repository(session)
    report = SyncReport()

    # Track which account IDs are present in config (to deactivate others)
    config_account_ids: set[int] = set()

    for tenant_name, tenant_cfg in config.tenants.items():
        # Upsert tenant
        tenant = repo.get_tenant_by_name(tenant_name)
        if tenant is None:
            tenant = repo.create_tenant(tenant_name, description=tenant_cfg.description)
            report.tenants_created += 1
        else:
            tenant.description = tenant_cfg.description
            report.tenants_updated += 1

        # Upsert cloud accounts for this tenant
        for acct_cfg in tenant_cfg.cloud_accounts:
            account = repo.get_cloud_account_by_name(tenant.id, acct_cfg.name)
            if account is None:
                account = repo.create_cloud_account(
                    tenant_id=tenant.id,
                    provider_type=acct_cfg.provider,
                    name=acct_cfg.name,
                    config=acct_cfg.credentials,
                )
                report.accounts_created += 1
            else:
                account.provider_type = acct_cfg.provider
                account.config = acct_cfg.credentials
                account.is_active = True
                report.accounts_updated += 1

            config_account_ids.add(account.id)

    # Deactivate accounts not present in config
    all_accounts = repo.list_cloud_accounts()
    for account in all_accounts:
        if account.id not in config_account_ids and account.is_active:
            account.is_active = False
            report.accounts_deactivated += 1

    session.flush()
    return report
