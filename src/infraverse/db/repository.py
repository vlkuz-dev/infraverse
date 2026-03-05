"""Data access layer for Infraverse database operations."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from infraverse.db.models import (
    Tenant,
    CloudAccount,
    VM,
    MonitoringHost,
    SyncRun,
)


class Repository:
    """Repository providing CRUD operations for all database models."""

    def __init__(self, session: Session):
        self.session = session

    # --- Tenant operations ---

    def create_tenant(self, name: str, description: str | None = None) -> Tenant:
        tenant = Tenant(name=name, description=description)
        self.session.add(tenant)
        self.session.flush()
        return tenant

    def get_tenant(self, tenant_id: int) -> Tenant | None:
        return self.session.get(Tenant, tenant_id)

    def get_tenant_by_name(self, name: str) -> Tenant | None:
        return self.session.query(Tenant).filter(Tenant.name == name).first()

    def list_tenants(self) -> list[Tenant]:
        return self.session.query(Tenant).order_by(Tenant.name).all()

    def delete_tenant(self, tenant_id: int) -> bool:
        tenant = self.session.get(Tenant, tenant_id)
        if tenant is None:
            return False
        self.session.delete(tenant)
        self.session.flush()
        return True

    # --- CloudAccount operations ---

    def create_cloud_account(
        self,
        tenant_id: int,
        provider_type: str,
        name: str,
        config: dict | None = None,
    ) -> CloudAccount:
        account = CloudAccount(
            tenant_id=tenant_id,
            provider_type=provider_type,
            name=name,
            config=config or {},
        )
        self.session.add(account)
        self.session.flush()
        return account

    def get_cloud_account(self, account_id: int) -> CloudAccount | None:
        return self.session.get(CloudAccount, account_id)

    def list_cloud_accounts(self) -> list[CloudAccount]:
        return self.session.query(CloudAccount).order_by(CloudAccount.name).all()

    def list_cloud_accounts_by_tenant(self, tenant_id: int) -> list[CloudAccount]:
        return (
            self.session.query(CloudAccount)
            .filter(CloudAccount.tenant_id == tenant_id)
            .order_by(CloudAccount.name)
            .all()
        )

    # --- VM operations ---

    def upsert_vm(
        self,
        cloud_account_id: int,
        external_id: str,
        name: str,
        status: str = "unknown",
        ip_addresses: list[str] | None = None,
        vcpus: int | None = None,
        memory_mb: int | None = None,
        cloud_name: str | None = None,
        folder_name: str | None = None,
    ) -> VM:
        vm = (
            self.session.query(VM)
            .filter(
                VM.cloud_account_id == cloud_account_id,
                VM.external_id == external_id,
            )
            .first()
        )
        now = datetime.now(timezone.utc)
        if vm is None:
            vm = VM(
                cloud_account_id=cloud_account_id,
                external_id=external_id,
                name=name,
                status=status,
                ip_addresses=ip_addresses or [],
                vcpus=vcpus,
                memory_mb=memory_mb,
                cloud_name=cloud_name,
                folder_name=folder_name,
                last_seen_at=now,
            )
            self.session.add(vm)
        else:
            vm.name = name
            vm.status = status
            vm.ip_addresses = ip_addresses or []
            vm.vcpus = vcpus
            vm.memory_mb = memory_mb
            vm.cloud_name = cloud_name
            vm.folder_name = folder_name
            vm.last_seen_at = now
        self.session.flush()
        return vm

    def get_vms_by_account(self, cloud_account_id: int) -> list[VM]:
        return (
            self.session.query(VM)
            .filter(VM.cloud_account_id == cloud_account_id)
            .order_by(VM.name)
            .all()
        )

    def get_all_vms(self) -> list[VM]:
        return self.session.query(VM).order_by(VM.name).all()

    def mark_vms_stale(
        self, cloud_account_id: int, seen_before: datetime
    ) -> int:
        """Mark VMs as offline if they weren't seen in the latest sync.

        Returns the number of VMs marked stale.
        """
        stale_vms = (
            self.session.query(VM)
            .filter(
                VM.cloud_account_id == cloud_account_id,
                (VM.last_seen_at < seen_before) | (VM.last_seen_at.is_(None)),
            )
            .all()
        )
        for vm in stale_vms:
            vm.status = "offline"
        self.session.flush()
        return len(stale_vms)

    # --- MonitoringHost operations ---

    def upsert_monitoring_host(
        self,
        source: str,
        external_id: str,
        name: str,
        status: str = "unknown",
        ip_addresses: list[str] | None = None,
    ) -> MonitoringHost:
        host = (
            self.session.query(MonitoringHost)
            .filter(
                MonitoringHost.source == source,
                MonitoringHost.external_id == external_id,
            )
            .first()
        )
        now = datetime.now(timezone.utc)
        if host is None:
            host = MonitoringHost(
                source=source,
                external_id=external_id,
                name=name,
                status=status,
                ip_addresses=ip_addresses or [],
                last_seen_at=now,
            )
            self.session.add(host)
        else:
            host.name = name
            host.status = status
            host.ip_addresses = ip_addresses or []
            host.last_seen_at = now
        self.session.flush()
        return host

    def get_all_monitoring_hosts(self) -> list[MonitoringHost]:
        return self.session.query(MonitoringHost).order_by(MonitoringHost.name).all()

    # --- SyncRun operations ---

    def create_sync_run(
        self,
        source: str,
        cloud_account_id: int | None = None,
    ) -> SyncRun:
        run = SyncRun(
            cloud_account_id=cloud_account_id,
            source=source,
            status="running",
        )
        self.session.add(run)
        self.session.flush()
        return run

    def update_sync_run(
        self,
        sync_run_id: int,
        status: str,
        items_found: int = 0,
        items_created: int = 0,
        items_updated: int = 0,
        error_message: str | None = None,
    ) -> SyncRun | None:
        run = self.session.get(SyncRun, sync_run_id)
        if run is None:
            return None
        run.status = status
        run.items_found = items_found
        run.items_created = items_created
        run.items_updated = items_updated
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        self.session.flush()
        return run

    def get_latest_sync_runs(self, limit: int = 10) -> list[SyncRun]:
        return (
            self.session.query(SyncRun)
            .order_by(SyncRun.started_at.desc())
            .limit(limit)
            .all()
        )
