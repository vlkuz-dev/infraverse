"""Data access layer for Infraverse database operations."""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from infraverse.db.models import (
    Tenant,
    CloudAccount,
    VM,
    MonitoringHost,
    NetBoxHost,
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

    def get_cloud_account_with_tenant(self, account_id: int) -> CloudAccount | None:
        """Get a single cloud account by ID with tenant eagerly loaded."""
        return (
            self.session.query(CloudAccount)
            .options(joinedload(CloudAccount.tenant))
            .filter(CloudAccount.id == account_id)
            .first()
        )

    def list_cloud_accounts(self) -> list[CloudAccount]:
        return self.session.query(CloudAccount).order_by(CloudAccount.name).all()

    def list_cloud_accounts_with_tenants(
        self, tenant_id: int | None = None
    ) -> list[CloudAccount]:
        """List cloud accounts with tenant and vms eagerly loaded.

        If tenant_id is provided, filters to that tenant's accounts only.
        """
        from sqlalchemy.orm import subqueryload

        query = (
            self.session.query(CloudAccount)
            .options(joinedload(CloudAccount.tenant), subqueryload(CloudAccount.vms))
        )
        if tenant_id is not None:
            query = query.filter(CloudAccount.tenant_id == tenant_id)
        return query.order_by(CloudAccount.name).all()

    def list_cloud_accounts_by_tenant(self, tenant_id: int) -> list[CloudAccount]:
        return (
            self.session.query(CloudAccount)
            .filter(CloudAccount.tenant_id == tenant_id)
            .order_by(CloudAccount.name)
            .all()
        )

    def get_cloud_account_by_name(
        self, tenant_id: int, name: str
    ) -> CloudAccount | None:
        return (
            self.session.query(CloudAccount)
            .filter(
                CloudAccount.tenant_id == tenant_id,
                CloudAccount.name == name,
            )
            .first()
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
        monitoring_exempt: bool = False,
        monitoring_exempt_reason: str | None = None,
    ) -> tuple[VM, bool]:
        """Upsert a VM record.

        Returns:
            Tuple of (VM, created) where created is True if the record was new.
        """
        vm = (
            self.session.query(VM)
            .filter(
                VM.cloud_account_id == cloud_account_id,
                VM.external_id == external_id,
            )
            .first()
        )
        now = datetime.now(timezone.utc)
        created = vm is None
        if created:
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
                monitoring_exempt=monitoring_exempt,
                monitoring_exempt_reason=monitoring_exempt_reason,
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
            vm.monitoring_exempt = monitoring_exempt
            vm.monitoring_exempt_reason = monitoring_exempt_reason
            vm.last_seen_at = now
        self.session.flush()
        return vm, created

    def get_vm_by_id(self, vm_id: int) -> VM | None:
        """Get a single VM by ID with cloud_account and tenant eagerly loaded."""
        return (
            self.session.query(VM)
            .options(joinedload(VM.cloud_account).joinedload(CloudAccount.tenant))
            .filter(VM.id == vm_id)
            .first()
        )

    def get_vms_by_account(self, cloud_account_id: int) -> list[VM]:
        return (
            self.session.query(VM)
            .filter(VM.cloud_account_id == cloud_account_id)
            .order_by(VM.name)
            .all()
        )

    def get_all_vms(
        self,
        tenant_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
    ) -> list[VM]:
        query = (
            self.session.query(VM)
            .options(joinedload(VM.cloud_account))
        )
        if account_id is not None:
            query = query.filter(VM.cloud_account_id == account_id)
        elif tenant_id is not None:
            query = query.join(CloudAccount).filter(
                CloudAccount.tenant_id == tenant_id
            )
        if status:
            query = query.filter(VM.status == status)
        return query.order_by(VM.name).all()

    def update_vm_sync_errors(
        self,
        vm_errors: dict[str, str],
        synced_vm_names: set[str],
    ) -> None:
        """Update last_sync_error on VM records after a NetBox sync.

        Args:
            vm_errors: Map of vm_name -> error_message for VMs that failed.
            synced_vm_names: Set of VM names that synced successfully
                (their errors should be cleared).
        """
        if not vm_errors and not synced_vm_names:
            return

        all_names = set(vm_errors.keys()) | synced_vm_names
        vms = (
            self.session.query(VM)
            .filter(VM.name.in_(all_names))
            .all()
        )
        for vm in vms:
            if vm.name in vm_errors:
                vm.last_sync_error = vm_errors[vm.name]
            elif vm.name in synced_vm_names:
                vm.last_sync_error = None
        self.session.flush()

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
        cloud_account_id: int | None = None,
    ) -> tuple[MonitoringHost, bool]:
        """Upsert a monitoring host record.

        Returns:
            Tuple of (MonitoringHost, created) where created is True if new.
        """
        host = (
            self.session.query(MonitoringHost)
            .filter(
                MonitoringHost.source == source,
                MonitoringHost.external_id == external_id,
            )
            .first()
        )
        now = datetime.now(timezone.utc)
        created = host is None
        if created:
            host = MonitoringHost(
                source=source,
                external_id=external_id,
                name=name,
                status=status,
                ip_addresses=ip_addresses or [],
                cloud_account_id=cloud_account_id,
                last_seen_at=now,
            )
            self.session.add(host)
        else:
            host.name = name
            host.status = status
            host.ip_addresses = ip_addresses or []
            host.cloud_account_id = cloud_account_id
            host.last_seen_at = now
        self.session.flush()
        return host, created

    def get_all_monitoring_hosts(self) -> list[MonitoringHost]:
        return self.session.query(MonitoringHost).order_by(MonitoringHost.name).all()

    def get_monitoring_hosts_by_account(
        self, cloud_account_id: int
    ) -> list[MonitoringHost]:
        return (
            self.session.query(MonitoringHost)
            .filter(MonitoringHost.cloud_account_id == cloud_account_id)
            .order_by(MonitoringHost.name)
            .all()
        )

    def get_monitoring_hosts_by_tenant(
        self, tenant_id: int
    ) -> list[MonitoringHost]:
        return (
            self.session.query(MonitoringHost)
            .join(CloudAccount, MonitoringHost.cloud_account_id == CloudAccount.id)
            .filter(CloudAccount.tenant_id == tenant_id)
            .order_by(MonitoringHost.name)
            .all()
        )

    def get_monitoring_host_by_name(
        self, name: str, cloud_account_id: int | None = None,
    ) -> MonitoringHost | None:
        """Find a monitoring host by exact name match (case-insensitive).

        Args:
            name: Host name to search for.
            cloud_account_id: If provided, restrict search to this account
                to avoid cross-tenant/account collisions.
        """
        query = (
            self.session.query(MonitoringHost)
            .filter(func.lower(MonitoringHost.name) == name.lower())
        )
        if cloud_account_id is not None:
            query = query.filter(
                MonitoringHost.cloud_account_id == cloud_account_id
            )
        return query.first()

    def mark_monitoring_hosts_stale(
        self, source: str, seen_before: datetime,
        cloud_account_ids: set[int] | None = None,
    ) -> int:
        """Mark monitoring hosts as offline if they weren't seen in the latest sync.

        Args:
            source: Monitoring source (e.g. "zabbix").
            seen_before: Cutoff time; hosts not seen since this time are stale.
            cloud_account_ids: If provided, only mark hosts belonging to these
                accounts. Hosts with NULL cloud_account_id are excluded when
                this filter is active.

        Returns the number of hosts marked stale.
        """
        query = (
            self.session.query(MonitoringHost)
            .filter(
                MonitoringHost.source == source,
                (MonitoringHost.last_seen_at < seen_before)
                | (MonitoringHost.last_seen_at.is_(None)),
            )
        )
        if cloud_account_ids is not None:
            query = query.filter(
                MonitoringHost.cloud_account_id.in_(cloud_account_ids)
            )
        stale_hosts = query.all()
        for host in stale_hosts:
            host.status = "offline"
        self.session.flush()
        return len(stale_hosts)

    # --- NetBoxHost operations ---

    def upsert_netbox_host(
        self,
        external_id: str,
        name: str,
        status: str = "unknown",
        ip_addresses: list[str] | None = None,
        cluster_name: str | None = None,
        vcpus: int | None = None,
        memory_mb: int | None = None,
        tenant_id: int | None = None,
    ) -> tuple[NetBoxHost, bool]:
        """Upsert a NetBox host record by external_id.

        Returns:
            Tuple of (NetBoxHost, created) where created is True if new.
        """
        host = (
            self.session.query(NetBoxHost)
            .filter(NetBoxHost.external_id == external_id)
            .first()
        )
        now = datetime.now(timezone.utc)
        created = host is None
        if created:
            host = NetBoxHost(
                external_id=external_id,
                name=name,
                status=status,
                ip_addresses=ip_addresses or [],
                cluster_name=cluster_name,
                vcpus=vcpus,
                memory_mb=memory_mb,
                tenant_id=tenant_id,
                last_seen_at=now,
            )
            self.session.add(host)
        else:
            host.name = name
            host.status = status
            host.ip_addresses = ip_addresses or []
            host.cluster_name = cluster_name
            host.vcpus = vcpus
            host.memory_mb = memory_mb
            host.tenant_id = tenant_id
            host.last_seen_at = now
        self.session.flush()
        return host, created

    def get_all_netbox_hosts(self) -> list[NetBoxHost]:
        return self.session.query(NetBoxHost).order_by(NetBoxHost.name).all()

    def get_netbox_hosts_by_tenant(self, tenant_id: int) -> list[NetBoxHost]:
        return (
            self.session.query(NetBoxHost)
            .filter(NetBoxHost.tenant_id == tenant_id)
            .order_by(NetBoxHost.name)
            .all()
        )

    def mark_netbox_hosts_stale(self, seen_before: datetime) -> int:
        """Mark NetBox hosts as offline if they weren't seen in the latest sync.

        Returns the number of hosts marked stale.
        """
        stale_hosts = (
            self.session.query(NetBoxHost)
            .filter(
                (NetBoxHost.last_seen_at < seen_before)
                | (NetBoxHost.last_seen_at.is_(None)),
            )
            .all()
        )
        for host in stale_hosts:
            host.status = "offline"
        self.session.flush()
        return len(stale_hosts)

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

    def get_sync_runs_by_account(
        self, cloud_account_id: int, limit: int = 10
    ) -> list[SyncRun]:
        return (
            self.session.query(SyncRun)
            .filter(SyncRun.cloud_account_id == cloud_account_id)
            .order_by(SyncRun.started_at.desc())
            .limit(limit)
            .all()
        )

    def get_latest_sync_run_by_source(
        self, source: str, tenant_id: int | None = None,
    ) -> SyncRun | None:
        """Get the most recent SyncRun for a given source.

        Args:
            source: Sync source (e.g. "netbox", "zabbix").
            tenant_id: If provided, only consider runs for this tenant's accounts
                (plus global runs with no account).
        """
        query = self.session.query(SyncRun).filter(SyncRun.source == source)
        if tenant_id is not None:
            query = query.outerjoin(
                CloudAccount, SyncRun.cloud_account_id == CloudAccount.id
            ).filter(
                (CloudAccount.tenant_id == tenant_id)
                | (SyncRun.cloud_account_id.is_(None))
            )
        return query.order_by(SyncRun.started_at.desc()).first()

    def get_latest_sync_runs(
        self, limit: int = 10, tenant_id: int | None = None,
    ) -> list[SyncRun]:
        """Get the most recent sync runs.

        Args:
            limit: Maximum number of runs to return.
            tenant_id: If provided, only return runs for this tenant's accounts
                (plus global runs with no account, e.g. zabbix).
        """
        query = self.session.query(SyncRun)
        if tenant_id is not None:
            query = query.outerjoin(
                CloudAccount, SyncRun.cloud_account_id == CloudAccount.id
            ).filter(
                (CloudAccount.tenant_id == tenant_id)
                | (SyncRun.cloud_account_id.is_(None))
            )
        return query.order_by(SyncRun.started_at.desc()).limit(limit).all()
