"""Data ingestion from cloud providers and monitoring systems into the database."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from infraverse.db.models import CloudAccount
from infraverse.db.repository import Repository
from infraverse.providers.base import CloudProvider, VMInfo
from infraverse.providers.zabbix import ZabbixClient, ZabbixHost

logger = logging.getLogger(__name__)


class DataIngestor:
    """Fetches data from cloud providers and monitoring systems, stores in DB.

    Each ingestion creates a SyncRun record to track status and counts.
    Provider failures are isolated - one failing provider doesn't stop others.
    """

    def __init__(self, session: Session):
        self.session = session
        self.repo = Repository(session)

    def ingest_cloud_vms(
        self,
        cloud_account: CloudAccount,
        provider: CloudProvider,
    ) -> int:
        """Fetch VMs from a cloud provider and upsert into DB.

        Args:
            cloud_account: The CloudAccount DB record for this provider.
            provider: A CloudProvider instance that can fetch VMs.

        Returns:
            Number of VMs found.

        Raises:
            Exception: Re-raises provider errors after recording them in SyncRun.
        """
        sync_run = self.repo.create_sync_run(
            source=cloud_account.provider_type,
            cloud_account_id=cloud_account.id,
        )
        self.session.commit()

        sync_start = datetime.now(timezone.utc)

        try:
            vms: list[VMInfo] = provider.fetch_vms()
        except Exception as exc:
            self.repo.update_sync_run(
                sync_run.id,
                status="failed",
                error_message=str(exc),
            )
            self.session.commit()
            logger.error(
                "Failed to fetch VMs for account %s: %s",
                cloud_account.name, exc,
            )
            raise

        items_created = 0
        items_updated = 0

        for vm_info in vms:
            _, created = self.repo.upsert_vm(
                cloud_account_id=cloud_account.id,
                external_id=vm_info.id,
                name=vm_info.name,
                status=vm_info.status,
                ip_addresses=vm_info.ip_addresses,
                vcpus=vm_info.vcpus,
                memory_mb=vm_info.memory_mb,
                cloud_name=vm_info.cloud_name,
                folder_name=vm_info.folder_name,
            )
            if created:
                items_created += 1
            else:
                items_updated += 1

        # Mark VMs not seen in this sync as stale
        self.repo.mark_vms_stale(cloud_account.id, sync_start)

        self.repo.update_sync_run(
            sync_run.id,
            status="success",
            items_found=len(vms),
            items_created=items_created,
            items_updated=items_updated,
        )
        self.session.commit()

        logger.info(
            "Ingested %d VMs for account %s (created=%d, updated=%d)",
            len(vms), cloud_account.name, items_created, items_updated,
        )
        return len(vms)

    def ingest_monitoring_hosts(
        self,
        zabbix_client: ZabbixClient,
    ) -> int:
        """Fetch hosts from Zabbix and upsert into DB.

        Args:
            zabbix_client: An authenticated ZabbixClient instance.

        Returns:
            Number of hosts found.

        Raises:
            Exception: Re-raises Zabbix errors after recording them in SyncRun.
        """
        sync_run = self.repo.create_sync_run(source="zabbix")
        self.session.commit()

        try:
            hosts: list[ZabbixHost] = zabbix_client.fetch_hosts()
        except Exception as exc:
            self.repo.update_sync_run(
                sync_run.id,
                status="failed",
                error_message=str(exc),
            )
            self.session.commit()
            logger.error("Failed to fetch Zabbix hosts: %s", exc)
            raise

        items_created = 0
        items_updated = 0

        for host in hosts:
            _, created = self.repo.upsert_monitoring_host(
                source="zabbix",
                external_id=host.hostid,
                name=host.name,
                status=host.status,
                ip_addresses=host.ip_addresses,
            )
            if created:
                items_created += 1
            else:
                items_updated += 1

        self.repo.update_sync_run(
            sync_run.id,
            status="success",
            items_found=len(hosts),
            items_created=items_created,
            items_updated=items_updated,
        )
        self.session.commit()

        logger.info("Ingested %d monitoring hosts from Zabbix", len(hosts))
        return len(hosts)

    def ingest_all(
        self,
        providers: dict[int, CloudProvider],
        zabbix_client: ZabbixClient | None = None,
    ) -> dict[str, str]:
        """Ingest data from all configured providers.

        Args:
            providers: Map of CloudAccount.id -> CloudProvider instance.
            zabbix_client: Optional ZabbixClient for monitoring hosts.

        Returns:
            Dict of source_name -> status ("success" or error message).
        """
        results: dict[str, str] = {}

        for account_id, provider in providers.items():
            account = self.repo.get_cloud_account(account_id)
            if account is None:
                results[f"account_{account_id}"] = "error: account not found"
                continue
            try:
                count = self.ingest_cloud_vms(account, provider)
                results[account.name] = "success"
                logger.info("Account %s: ingested %d VMs", account.name, count)
            except Exception as exc:
                results[account.name] = f"error: {exc}"
                logger.error("Account %s: ingestion failed: %s", account.name, exc)

        if zabbix_client is not None:
            try:
                count = self.ingest_monitoring_hosts(zabbix_client)
                results["zabbix"] = "success"
                logger.info("Zabbix: ingested %d hosts", count)
            except Exception as exc:
                results["zabbix"] = f"error: {exc}"
                logger.error("Zabbix: ingestion failed: %s", exc)

        return results
