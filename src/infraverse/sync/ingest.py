"""Data ingestion from cloud providers and monitoring systems into the database."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from infraverse.config_file import MonitoringExclusionRule
from infraverse.db.models import CloudAccount
from infraverse.db.repository import Repository
from infraverse.providers.base import CloudProvider, VMInfo
from infraverse.sync.exclusions import check_monitoring_exclusion
from infraverse.sync.monitoring import check_all_vms_monitoring

logger = logging.getLogger(__name__)


class DataIngestor:
    """Fetches data from cloud providers and monitoring systems, stores in DB.

    Each ingestion creates a SyncRun record to track status and counts.
    Provider failures are isolated - one failing provider doesn't stop others.
    """

    def __init__(
        self,
        session: Session,
        exclusion_rules: list[MonitoringExclusionRule] | None = None,
    ):
        self.session = session
        self.repo = Repository(session)
        self.exclusion_rules = exclusion_rules or []

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

        try:
            for vm_info in vms:
                is_exempt, exempt_reason = check_monitoring_exclusion(
                    vm_info.name, vm_info.status, self.exclusion_rules,
                )
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
                    monitoring_exempt=is_exempt,
                    monitoring_exempt_reason=exempt_reason,
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
        except Exception as exc:
            self.session.rollback()
            self.repo.update_sync_run(
                sync_run.id,
                status="failed",
                error_message=str(exc),
            )
            self.session.commit()
            logger.error(
                "Failed to upsert VMs for account %s: %s",
                cloud_account.name, exc,
            )
            raise

        logger.info(
            "Ingested %d VMs for account %s (created=%d, updated=%d)",
            len(vms), cloud_account.name, items_created, items_updated,
        )
        return len(vms)

    def ingest_monitoring_hosts(
        self,
        vms: list,
        zabbix_client,
    ) -> int:
        """Check monitoring status for known VMs and store results in DB.

        Instead of bulk-fetching all Zabbix hosts, queries Zabbix per VM
        by name (with IP fallback) and stores found hosts as MonitoringHost
        records linked to the VM's cloud account.

        Args:
            vms: List of VM objects (with name, ip_addresses, cloud_account_id).
            zabbix_client: ZabbixClient with search_host_by_name/ip methods.

        Returns:
            Number of VMs found to be monitored.

        Raises:
            Exception: Re-raises Zabbix errors after recording them in SyncRun.
        """
        sync_run = self.repo.create_sync_run(source="zabbix")
        self.session.commit()

        sync_start = datetime.now(timezone.utc)

        try:
            results = check_all_vms_monitoring(vms, zabbix_client)
        except Exception as exc:
            self.repo.update_sync_run(
                sync_run.id,
                status="failed",
                error_message=str(exc),
            )
            self.session.commit()
            logger.error("Failed to check VM monitoring: %s", exc)
            raise

        items_created = 0
        items_updated = 0
        found_count = 0

        try:
            for vm, result in zip(vms, results):
                if not result.found:
                    continue
                found_count += 1
                _, created = self.repo.upsert_monitoring_host(
                    source="zabbix",
                    external_id=result.host.hostid,
                    name=vm.name,
                    status=result.host.status,
                    ip_addresses=result.host.ip_addresses,
                    cloud_account_id=vm.cloud_account_id,
                )
                if created:
                    items_created += 1
                else:
                    items_updated += 1

            # Mark monitoring hosts not seen in this sync as stale,
            # scoped to only the accounts whose VMs were actually checked
            checked_account_ids = {vm.cloud_account_id for vm in vms}
            self.repo.mark_monitoring_hosts_stale(
                "zabbix", sync_start,
                cloud_account_ids=checked_account_ids,
            )

            self.repo.update_sync_run(
                sync_run.id,
                status="success",
                items_found=found_count,
                items_created=items_created,
                items_updated=items_updated,
            )
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            self.repo.update_sync_run(
                sync_run.id,
                status="failed",
                error_message=str(exc),
            )
            self.session.commit()
            logger.error("Failed to store monitoring results: %s", exc)
            raise

        logger.info(
            "Checked %d VMs for monitoring, %d found monitored",
            len(vms), found_count,
        )
        return found_count

    def ingest_netbox_hosts(self, netbox_client) -> int:
        """Fetch VMs from NetBox and upsert as NetBoxHost records in DB.

        Args:
            netbox_client: A NetBoxClient with fetch_all_vms() method.

        Returns:
            Number of VMs found.

        Raises:
            Exception: Re-raises NetBox errors after recording them in SyncRun.
        """
        sync_run = self.repo.create_sync_run(source="netbox")
        self.session.commit()

        sync_start = datetime.now(timezone.utc)

        try:
            vms = netbox_client.fetch_all_vms()
        except Exception as exc:
            self.repo.update_sync_run(
                sync_run.id,
                status="failed",
                error_message=str(exc),
            )
            self.session.commit()
            logger.error("Failed to fetch VMs from NetBox: %s", exc)
            raise

        items_created = 0
        items_updated = 0

        # Build tenant name -> tenant_id mapping for resolving NetBox tenant names
        all_tenants = self.repo.list_tenants()
        tenant_name_to_id = {t.name: t.id for t in all_tenants}

        try:
            for vm_info in vms:
                tenant_id = tenant_name_to_id.get(vm_info.tenant_name)
                _, created = self.repo.upsert_netbox_host(
                    external_id=vm_info.id,
                    name=vm_info.name,
                    status=vm_info.status,
                    ip_addresses=vm_info.ip_addresses,
                    cluster_name=vm_info.folder_name,
                    vcpus=vm_info.vcpus,
                    memory_mb=vm_info.memory_mb,
                    tenant_id=tenant_id,
                )
                if created:
                    items_created += 1
                else:
                    items_updated += 1

            self.repo.mark_netbox_hosts_stale(sync_start)

            self.repo.update_sync_run(
                sync_run.id,
                status="success",
                items_found=len(vms),
                items_created=items_created,
                items_updated=items_updated,
            )
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            self.repo.update_sync_run(
                sync_run.id,
                status="failed",
                error_message=str(exc),
            )
            self.session.commit()
            logger.error("Failed to store NetBox hosts: %s", exc)
            raise

        logger.info(
            "Ingested %d VMs from NetBox (created=%d, updated=%d)",
            len(vms), items_created, items_updated,
        )
        return len(vms)

    def ingest_all(
        self,
        providers: dict[int, CloudProvider],
        zabbix_client=None,
    ) -> dict[str, str]:
        """Ingest data from all configured providers.

        Args:
            providers: Map of CloudAccount.id -> CloudProvider instance.
            zabbix_client: Optional ZabbixClient for per-VM monitoring checks.

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
                self.session.rollback()
                results[account.name] = f"error: {exc}"
                logger.error("Account %s: ingestion failed: %s", account.name, exc)

        if zabbix_client is not None:
            # Only check VMs from active accounts, excluding monitoring-exempt VMs
            active_account_ids = set(providers.keys())
            all_vms = [
                vm for vm in self.repo.get_all_vms()
                if vm.cloud_account_id in active_account_ids
                and not vm.monitoring_exempt
            ]
            if not all_vms:
                logger.info("No VMs to check for monitoring, skipping")
            else:
                try:
                    count = self.ingest_monitoring_hosts(all_vms, zabbix_client)
                    results["zabbix"] = "success"
                    logger.info("Zabbix: checked %d VMs, %d monitored", len(all_vms), count)
                except Exception as exc:
                    self.session.rollback()
                    results["zabbix"] = f"error: {exc}"
                    logger.error("Zabbix: monitoring check failed: %s", exc)

        return results
