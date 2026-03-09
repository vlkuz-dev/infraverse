"""Tests for the Repository data access layer."""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infraverse.db.models import Base, CloudAccount, MonitoringHost, VM
from infraverse.db.repository import Repository


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine with FK enforcement."""
    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    """Create a database session for testing."""
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def repo(session):
    """Create a Repository instance."""
    return Repository(session)


# --- Tenant CRUD ---


class TestTenantCRUD:
    def test_create_tenant(self, repo, session):
        tenant = repo.create_tenant("Acme Corp", description="Main customer")
        assert tenant.id is not None
        assert tenant.name == "Acme Corp"
        assert tenant.description == "Main customer"

    def test_create_tenant_no_description(self, repo):
        tenant = repo.create_tenant("Bare Tenant")
        assert tenant.description is None

    def test_get_tenant(self, repo):
        created = repo.create_tenant("Get Me")
        fetched = repo.get_tenant(created.id)
        assert fetched is not None
        assert fetched.name == "Get Me"

    def test_get_tenant_not_found(self, repo):
        assert repo.get_tenant(99999) is None

    def test_get_tenant_by_name(self, repo):
        repo.create_tenant("By Name Corp")
        found = repo.get_tenant_by_name("By Name Corp")
        assert found is not None
        assert found.name == "By Name Corp"

    def test_get_tenant_by_name_not_found(self, repo):
        assert repo.get_tenant_by_name("Nonexistent") is None

    def test_list_tenants(self, repo):
        repo.create_tenant("Zeta")
        repo.create_tenant("Alpha")
        repo.create_tenant("Middle")
        tenants = repo.list_tenants()
        names = [t.name for t in tenants]
        assert names == ["Alpha", "Middle", "Zeta"]

    def test_list_tenants_empty(self, repo):
        assert repo.list_tenants() == []

    def test_delete_tenant(self, repo):
        tenant = repo.create_tenant("Delete Me")
        tid = tenant.id
        assert repo.delete_tenant(tid) is True
        assert repo.get_tenant(tid) is None

    def test_delete_tenant_not_found(self, repo):
        assert repo.delete_tenant(99999) is False

    def test_delete_tenant_cascades_accounts(self, repo, session):
        tenant = repo.create_tenant("Cascade Parent")
        repo.create_cloud_account(tenant.id, "yandex_cloud", "YC")
        session.commit()
        repo.delete_tenant(tenant.id)
        session.commit()
        assert session.query(CloudAccount).count() == 0

    def test_create_duplicate_tenant_name(self, repo, session):
        repo.create_tenant("Dup Name")
        session.commit()
        with pytest.raises(IntegrityError):
            repo.create_tenant("Dup Name")


# --- CloudAccount CRUD ---


class TestCloudAccountCRUD:
    @pytest.fixture
    def tenant(self, repo):
        return repo.create_tenant("Account Tenant")

    def test_create_cloud_account(self, repo, tenant):
        account = repo.create_cloud_account(
            tenant.id, "yandex_cloud", "YC Russia"
        )
        assert account.id is not None
        assert account.provider_type == "yandex_cloud"
        assert account.name == "YC Russia"
        assert account.config == {}

    def test_create_cloud_account_with_config(self, repo, tenant):
        config = {"endpoint": "https://api.yandex.net"}
        account = repo.create_cloud_account(
            tenant.id, "yandex_cloud", "YC Custom", config=config
        )
        assert account.config == {"endpoint": "https://api.yandex.net"}

    def test_get_cloud_account(self, repo, tenant):
        created = repo.create_cloud_account(tenant.id, "vcloud", "vCloud DC")
        fetched = repo.get_cloud_account(created.id)
        assert fetched is not None
        assert fetched.name == "vCloud DC"

    def test_get_cloud_account_loads_tenant(self, repo, tenant):
        created = repo.create_cloud_account(tenant.id, "vcloud", "vCloud DC")
        fetched = repo.get_cloud_account(created.id)
        assert fetched is not None
        assert fetched.tenant is not None
        assert fetched.tenant.name == tenant.name

    def test_get_cloud_account_not_found(self, repo):
        assert repo.get_cloud_account(99999) is None

    def test_list_cloud_accounts(self, repo, tenant):
        repo.create_cloud_account(tenant.id, "vcloud", "Z-Cloud")
        repo.create_cloud_account(tenant.id, "yandex_cloud", "A-Cloud")
        accounts = repo.list_cloud_accounts()
        names = [a.name for a in accounts]
        assert names == ["A-Cloud", "Z-Cloud"]

    def test_list_cloud_accounts_empty(self, repo):
        assert repo.list_cloud_accounts() == []

    def test_list_cloud_accounts_by_tenant(self, repo):
        t1 = repo.create_tenant("Tenant A")
        t2 = repo.create_tenant("Tenant B")
        repo.create_cloud_account(t1.id, "yandex_cloud", "T1 YC")
        repo.create_cloud_account(t1.id, "vcloud", "T1 vCloud")
        repo.create_cloud_account(t2.id, "netbox", "T2 NetBox")
        t1_accounts = repo.list_cloud_accounts(tenant_id=t1.id)
        t2_accounts = repo.list_cloud_accounts(tenant_id=t2.id)
        assert len(t1_accounts) == 2
        assert len(t2_accounts) == 1
        assert t2_accounts[0].name == "T2 NetBox"

    def test_list_cloud_accounts_by_tenant_empty(self, repo):
        t = repo.create_tenant("Empty Tenant")
        assert repo.list_cloud_accounts(tenant_id=t.id) == []

    def test_list_cloud_accounts_with_relations(self, repo):
        t = repo.create_tenant("Relations Tenant")
        acc = repo.create_cloud_account(t.id, "yandex_cloud", "YC Rel")
        repo.upsert_vm(acc.id, "fhm-1", "vm-1", status="active")
        accounts = repo.list_cloud_accounts(with_relations=True)
        assert len(accounts) == 1
        assert accounts[0].tenant is not None
        assert accounts[0].tenant.name == "Relations Tenant"
        assert len(accounts[0].vms) == 1

    def test_list_cloud_accounts_with_relations_and_tenant_id(self, repo):
        t1 = repo.create_tenant("Rel Tenant A")
        t2 = repo.create_tenant("Rel Tenant B")
        repo.create_cloud_account(t1.id, "yandex_cloud", "T1 YC")
        repo.create_cloud_account(t2.id, "vcloud", "T2 VC")
        accounts = repo.list_cloud_accounts(tenant_id=t1.id, with_relations=True)
        assert len(accounts) == 1
        assert accounts[0].tenant.name == "Rel Tenant A"

    def test_create_account_missing_tenant(self, repo, session):
        with pytest.raises(IntegrityError):
            repo.create_cloud_account(99999, "yandex_cloud", "Orphan")


# --- VM operations ---


class TestVMOperations:
    @pytest.fixture
    def account(self, repo):
        tenant = repo.create_tenant("VM Tenant")
        return repo.create_cloud_account(tenant.id, "yandex_cloud", "YC VMs")

    def test_upsert_vm_create(self, repo, account):
        vm, created = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-001",
            name="web-server",
            status="active",
            ip_addresses=["10.0.0.1"],
            vcpus=4,
            memory_mb=8192,
            cloud_name="my-cloud",
            folder_name="prod",
        )
        assert vm.id is not None
        assert created is True
        assert vm.name == "web-server"
        assert vm.status == "active"
        assert vm.ip_addresses == ["10.0.0.1"]
        assert vm.vcpus == 4
        assert vm.memory_mb == 8192
        assert vm.cloud_name == "my-cloud"
        assert vm.folder_name == "prod"
        assert vm.last_seen_at is not None

    def test_upsert_vm_update(self, repo, account):
        repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-upd",
            name="old-name",
            status="active",
        )
        vm, created = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-upd",
            name="new-name",
            status="offline",
            ip_addresses=["10.0.0.2"],
            vcpus=8,
            memory_mb=16384,
        )
        assert created is False
        assert vm.name == "new-name"
        assert vm.status == "offline"
        assert vm.ip_addresses == ["10.0.0.2"]
        assert vm.vcpus == 8
        assert vm.memory_mb == 16384

    def test_upsert_vm_preserves_id_on_update(self, repo, account):
        vm1, _ = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-id",
            name="orig",
        )
        vm2, _ = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-id",
            name="updated",
        )
        assert vm1.id == vm2.id

    def test_upsert_vm_default_status(self, repo, account):
        vm, _ = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-def",
            name="default-vm",
        )
        assert vm.status == "unknown"

    def test_upsert_vm_default_ip_empty(self, repo, account):
        vm, _ = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-noip",
            name="no-ip",
        )
        assert vm.ip_addresses == []

    def test_get_all_vms_by_account(self, repo, account):
        repo.upsert_vm(account.id, "fhm-z", "z-server")
        repo.upsert_vm(account.id, "fhm-a", "a-server")
        vms = repo.get_all_vms(account_id=account.id)
        names = [v.name for v in vms]
        assert names == ["a-server", "z-server"]

    def test_get_all_vms_by_account_empty(self, repo, account):
        assert repo.get_all_vms(account_id=account.id) == []

    def test_get_all_vms(self, repo):
        t = repo.create_tenant("All VMs Tenant")
        acc1 = repo.create_cloud_account(t.id, "yandex_cloud", "YC1")
        acc2 = repo.create_cloud_account(t.id, "vcloud", "VC1")
        repo.upsert_vm(acc1.id, "fhm-1", "yc-vm")
        repo.upsert_vm(acc2.id, "vc-1", "vc-vm")
        vms = repo.get_all_vms()
        assert len(vms) == 2
        names = [v.name for v in vms]
        assert "yc-vm" in names
        assert "vc-vm" in names

    def test_get_all_vms_empty(self, repo):
        assert repo.get_all_vms() == []

    def test_mark_vms_stale(self, repo, account):
        # Create two VMs with different last_seen_at
        old_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        vm_old, _ = repo.upsert_vm(account.id, "fhm-old", "old-vm", status="active")
        # Manually set last_seen_at to past
        vm_old.last_seen_at = old_time
        repo.session.flush()

        # Create a fresh VM (last_seen_at is now)
        repo.upsert_vm(account.id, "fhm-new", "new-vm", status="active")

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=5)
        count = repo.mark_vms_stale(account.id, cutoff)
        assert count == 1

        vms = repo.get_all_vms(account_id=account.id)
        statuses = {v.name: v.status for v in vms}
        assert statuses["old-vm"] == "offline"
        assert statuses["new-vm"] == "active"

    def test_mark_vms_stale_null_last_seen(self, repo, account, session):
        vm = VM(
            cloud_account_id=account.id,
            external_id="fhm-null",
            name="null-seen-vm",
            status="active",
        )
        session.add(vm)
        session.flush()

        cutoff = datetime.now(timezone.utc)
        count = repo.mark_vms_stale(account.id, cutoff)
        assert count == 1
        session.refresh(vm)
        assert vm.status == "offline"

    def test_mark_vms_stale_none_stale(self, repo, account):
        repo.upsert_vm(account.id, "fhm-fresh", "fresh-vm", status="active")
        cutoff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        count = repo.mark_vms_stale(account.id, cutoff)
        assert count == 0

    def test_mark_vms_stale_scoped_to_account(self, repo):
        t = repo.create_tenant("Stale Scope Tenant")
        acc1 = repo.create_cloud_account(t.id, "yandex_cloud", "Acc1")
        acc2 = repo.create_cloud_account(t.id, "yandex_cloud", "Acc2")
        vm1, _ = repo.upsert_vm(acc1.id, "fhm-1", "vm1", status="active")
        vm1.last_seen_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        vm2, _ = repo.upsert_vm(acc2.id, "fhm-2", "vm2", status="active")
        vm2.last_seen_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        repo.session.flush()

        cutoff = datetime.now(timezone.utc)
        count = repo.mark_vms_stale(acc1.id, cutoff)
        assert count == 1

        repo.session.refresh(vm1)
        repo.session.refresh(vm2)
        assert vm1.status == "offline"
        assert vm2.status == "active"  # Unaffected - different account


# --- VM sync error operations ---


class TestVMSyncErrors:
    @pytest.fixture
    def account(self, repo):
        tenant = repo.create_tenant("Sync Error Tenant")
        return repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Sync Errors")

    def test_update_vm_sync_errors_sets_error(self, repo, account):
        vm, _ = repo.upsert_vm(account.id, "vm-001", "broken-vm", status="active")
        repo.update_vm_sync_errors({"broken-vm": "400 Bad Request"}, set())
        repo.session.refresh(vm)
        assert vm.last_sync_error == "400 Bad Request"

    def test_update_vm_sync_errors_clears_on_success(self, repo, account):
        vm, _ = repo.upsert_vm(account.id, "vm-001", "fixed-vm", status="active")
        vm.last_sync_error = "old error"
        repo.session.flush()
        repo.update_vm_sync_errors({}, {"fixed-vm"})
        repo.session.refresh(vm)
        assert vm.last_sync_error is None

    def test_update_vm_sync_errors_error_wins_over_success(self, repo, account):
        """If a VM appears in both errors and synced, error takes priority."""
        vm, _ = repo.upsert_vm(account.id, "vm-001", "conflict-vm", status="active")
        repo.update_vm_sync_errors(
            {"conflict-vm": "new error"}, {"conflict-vm"},
        )
        repo.session.refresh(vm)
        assert vm.last_sync_error == "new error"

    def test_update_vm_sync_errors_no_op_when_empty(self, repo, account):
        vm, _ = repo.upsert_vm(account.id, "vm-001", "untouched-vm", status="active")
        repo.update_vm_sync_errors({}, set())
        repo.session.refresh(vm)
        assert vm.last_sync_error is None

    def test_update_vm_sync_errors_unknown_vm_ignored(self, repo, account):
        """VMs not in the database are silently ignored."""
        repo.update_vm_sync_errors({"nonexistent-vm": "error"}, set())
        # No exception raised


# --- VM monitoring exempt operations ---


class TestVMMonitoringExempt:
    @pytest.fixture
    def account(self, repo):
        tenant = repo.create_tenant("Exempt Tenant")
        return repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Exempt")

    def test_upsert_vm_default_not_exempt(self, repo, account):
        vm, created = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-def-exempt",
            name="default-exempt-vm",
            status="active",
        )
        assert created is True
        assert vm.monitoring_exempt is False
        assert vm.monitoring_exempt_reason is None

    def test_upsert_vm_create_exempt(self, repo, account):
        vm, created = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-exempt",
            name="k8s-node",
            status="active",
            monitoring_exempt=True,
            monitoring_exempt_reason="K8s node",
        )
        assert created is True
        assert vm.monitoring_exempt is True
        assert vm.monitoring_exempt_reason == "K8s node"

    def test_upsert_vm_update_sets_exempt(self, repo, account):
        vm, _ = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-set-exempt",
            name="soon-exempt-vm",
            status="active",
        )
        assert vm.monitoring_exempt is False
        assert vm.monitoring_exempt_reason is None

        vm, created = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-set-exempt",
            name="soon-exempt-vm",
            status="active",
            monitoring_exempt=True,
            monitoring_exempt_reason="K8s node",
        )
        assert created is False
        assert vm.monitoring_exempt is True
        assert vm.monitoring_exempt_reason == "K8s node"

    def test_upsert_vm_update_clears_exempt(self, repo, account):
        vm, _ = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-clear-exempt",
            name="was-exempt-vm",
            status="active",
            monitoring_exempt=True,
            monitoring_exempt_reason="K8s node",
        )
        assert vm.monitoring_exempt is True
        assert vm.monitoring_exempt_reason == "K8s node"

        vm, created = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="fhm-clear-exempt",
            name="was-exempt-vm",
            status="active",
            monitoring_exempt=False,
            monitoring_exempt_reason=None,
        )
        assert created is False
        assert vm.monitoring_exempt is False
        assert vm.monitoring_exempt_reason is None


# --- MonitoringHost operations ---


class TestMonitoringHostOperations:
    def test_upsert_monitoring_host_create(self, repo):
        host, created = repo.upsert_monitoring_host(
            source="zabbix",
            external_id="zbx-100",
            name="monitor-1",
            status="active",
            ip_addresses=["10.0.0.5"],
        )
        assert host.id is not None
        assert created is True
        assert host.source == "zabbix"
        assert host.name == "monitor-1"
        assert host.status == "active"
        assert host.ip_addresses == ["10.0.0.5"]
        assert host.last_seen_at is not None

    def test_upsert_monitoring_host_update(self, repo):
        repo.upsert_monitoring_host("zabbix", "zbx-upd", "old-host", "active")
        host, created = repo.upsert_monitoring_host(
            "zabbix", "zbx-upd", "new-host", "offline", ["10.0.0.6"]
        )
        assert created is False
        assert host.name == "new-host"
        assert host.status == "offline"
        assert host.ip_addresses == ["10.0.0.6"]

    def test_upsert_monitoring_host_preserves_id(self, repo):
        h1, _ = repo.upsert_monitoring_host("zabbix", "zbx-id", "host1")
        h2, _ = repo.upsert_monitoring_host("zabbix", "zbx-id", "host2")
        assert h1.id == h2.id

    def test_upsert_monitoring_host_default_status(self, repo):
        host, _ = repo.upsert_monitoring_host("zabbix", "zbx-def", "def-host")
        assert host.status == "unknown"

    def test_upsert_monitoring_host_different_sources(self, repo):
        h1, _ = repo.upsert_monitoring_host("zabbix", "same-id", "zbx-host")
        h2, _ = repo.upsert_monitoring_host("prometheus", "same-id", "prom-host")
        assert h1.id != h2.id

    def test_get_all_monitoring_hosts(self, repo):
        repo.upsert_monitoring_host("zabbix", "zbx-1", "z-host")
        repo.upsert_monitoring_host("zabbix", "zbx-2", "a-host")
        hosts = repo.get_all_monitoring_hosts()
        names = [h.name for h in hosts]
        assert names == ["a-host", "z-host"]

    def test_get_all_monitoring_hosts_empty(self, repo):
        assert repo.get_all_monitoring_hosts() == []

    def test_mark_monitoring_hosts_stale(self, repo):
        old_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        host_old, _ = repo.upsert_monitoring_host("zabbix", "zbx-old", "old-host", "active")
        host_old.last_seen_at = old_time
        repo.session.flush()

        # Create a fresh host
        repo.upsert_monitoring_host("zabbix", "zbx-new", "new-host", "active")

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=5)
        count = repo.mark_monitoring_hosts_stale("zabbix", cutoff)
        assert count == 1

        hosts = repo.get_all_monitoring_hosts()
        statuses = {h.name: h.status for h in hosts}
        assert statuses["old-host"] == "offline"
        assert statuses["new-host"] == "active"

    def test_mark_monitoring_hosts_stale_null_last_seen(self, repo, session):
        host = MonitoringHost(
            source="zabbix",
            external_id="zbx-null",
            name="null-host",
            status="active",
            last_seen_at=None,
        )
        session.add(host)
        session.flush()

        cutoff = datetime.now(timezone.utc)
        count = repo.mark_monitoring_hosts_stale("zabbix", cutoff)
        assert count == 1
        session.refresh(host)
        assert host.status == "offline"

    def test_get_monitoring_host_by_name(self, repo):
        repo.upsert_monitoring_host("zabbix", "zbx-1", "web-server-1", "active")
        host = repo.get_monitoring_host_by_name("web-server-1")
        assert host is not None
        assert host.name == "web-server-1"

    def test_get_monitoring_host_by_name_case_insensitive(self, repo):
        repo.upsert_monitoring_host("zabbix", "zbx-1", "Web-Server-1", "active")
        host = repo.get_monitoring_host_by_name("web-server-1")
        assert host is not None
        assert host.name == "Web-Server-1"

    def test_get_monitoring_host_by_name_exact_match_ignores_sql_wildcards(self, repo):
        repo.upsert_monitoring_host("zabbix", "zbx-1", "web_server%1", "active")
        assert repo.get_monitoring_host_by_name("web_server%1") is not None
        # _ and % must NOT act as SQL LIKE wildcards
        assert repo.get_monitoring_host_by_name("webXserverX1") is None
        assert repo.get_monitoring_host_by_name("web_server1") is None

    def test_get_monitoring_host_by_name_not_found(self, repo):
        assert repo.get_monitoring_host_by_name("nonexistent") is None

    def test_mark_monitoring_hosts_stale_scoped_to_source(self, repo):
        old_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        h1, _ = repo.upsert_monitoring_host("zabbix", "zbx-1", "zbx-host", "active")
        h2, _ = repo.upsert_monitoring_host("prometheus", "prom-1", "prom-host", "active")
        h1.last_seen_at = old_time
        h2.last_seen_at = old_time
        repo.session.flush()

        cutoff = datetime.now(timezone.utc)
        count = repo.mark_monitoring_hosts_stale("zabbix", cutoff)
        assert count == 1

        repo.session.refresh(h1)
        repo.session.refresh(h2)
        assert h1.status == "offline"
        assert h2.status == "active"  # not affected (different source)

    def test_upsert_monitoring_host_with_cloud_account_id(self, repo):
        tenant = repo.create_tenant("Monitoring Tenant")
        account = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Mon")
        host, created = repo.upsert_monitoring_host(
            source="zabbix",
            external_id="zbx-acc-1",
            name="monitored-vm",
            status="active",
            ip_addresses=["10.0.0.1"],
            cloud_account_id=account.id,
        )
        assert created is True
        assert host.cloud_account_id == account.id

    def test_upsert_monitoring_host_update_cloud_account_id(self, repo):
        tenant = repo.create_tenant("Mon Update Tenant")
        acc1 = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC1")
        acc2 = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC2")

        host, _ = repo.upsert_monitoring_host(
            "zabbix", "zbx-upd-acc", "host1", "active",
            cloud_account_id=acc1.id,
        )
        assert host.cloud_account_id == acc1.id

        host, created = repo.upsert_monitoring_host(
            "zabbix", "zbx-upd-acc", "host1-updated", "active",
            cloud_account_id=acc2.id,
        )
        assert created is False
        assert host.cloud_account_id == acc2.id

    def test_upsert_monitoring_host_without_cloud_account_id(self, repo):
        host, created = repo.upsert_monitoring_host(
            "zabbix", "zbx-no-acc", "no-acc-host", "active",
        )
        assert created is True
        assert host.cloud_account_id is None

    def test_get_monitoring_hosts_by_account(self, repo):
        tenant = repo.create_tenant("By Account Tenant")
        acc1 = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC1")
        acc2 = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC2")

        repo.upsert_monitoring_host(
            "zabbix", "zbx-a1", "host-a1", "active", cloud_account_id=acc1.id,
        )
        repo.upsert_monitoring_host(
            "zabbix", "zbx-a2", "host-a2", "active", cloud_account_id=acc1.id,
        )
        repo.upsert_monitoring_host(
            "zabbix", "zbx-b1", "host-b1", "active", cloud_account_id=acc2.id,
        )
        repo.upsert_monitoring_host(
            "zabbix", "zbx-none", "host-none", "active",
        )

        acc1_hosts = repo.get_monitoring_hosts_by_account(acc1.id)
        assert len(acc1_hosts) == 2
        names = [h.name for h in acc1_hosts]
        assert "host-a1" in names
        assert "host-a2" in names

        acc2_hosts = repo.get_monitoring_hosts_by_account(acc2.id)
        assert len(acc2_hosts) == 1
        assert acc2_hosts[0].name == "host-b1"

    def test_get_monitoring_hosts_by_account_empty(self, repo):
        tenant = repo.create_tenant("Empty Mon Tenant")
        account = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Empty")
        assert repo.get_monitoring_hosts_by_account(account.id) == []

    def test_get_monitoring_hosts_by_account_ordered(self, repo):
        tenant = repo.create_tenant("Ordered Mon Tenant")
        account = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Ord")
        repo.upsert_monitoring_host(
            "zabbix", "zbx-z", "z-host", "active", cloud_account_id=account.id,
        )
        repo.upsert_monitoring_host(
            "zabbix", "zbx-a", "a-host", "active", cloud_account_id=account.id,
        )
        hosts = repo.get_monitoring_hosts_by_account(account.id)
        names = [h.name for h in hosts]
        assert names == ["a-host", "z-host"]

    def test_get_monitoring_hosts_by_tenant(self, repo):
        t1 = repo.create_tenant("Mon Tenant A")
        t2 = repo.create_tenant("Mon Tenant B")
        a1 = repo.create_cloud_account(t1.id, "yandex_cloud", "A YC")
        a2 = repo.create_cloud_account(t2.id, "yandex_cloud", "B YC")
        repo.upsert_monitoring_host(
            "zabbix", "z-1", "host-a1", "active", cloud_account_id=a1.id,
        )
        repo.upsert_monitoring_host(
            "zabbix", "z-2", "host-a2", "active", cloud_account_id=a1.id,
        )
        repo.upsert_monitoring_host(
            "zabbix", "z-3", "host-b1", "active", cloud_account_id=a2.id,
        )
        t1_hosts = repo.get_monitoring_hosts_by_tenant(t1.id)
        assert len(t1_hosts) == 2
        assert {h.name for h in t1_hosts} == {"host-a1", "host-a2"}

        t2_hosts = repo.get_monitoring_hosts_by_tenant(t2.id)
        assert len(t2_hosts) == 1
        assert t2_hosts[0].name == "host-b1"

    def test_get_monitoring_hosts_by_tenant_empty(self, repo):
        tenant = repo.create_tenant("Empty Mon Tenant")
        repo.create_cloud_account(tenant.id, "yandex_cloud", "No Mon")
        assert repo.get_monitoring_hosts_by_tenant(tenant.id) == []

    def test_get_monitoring_hosts_by_tenant_excludes_unlinked(self, repo):
        """MonitoringHost without cloud_account_id is not returned by tenant query."""
        tenant = repo.create_tenant("Unlinked Mon Tenant")
        repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Unlinked")
        repo.upsert_monitoring_host(
            "zabbix", "z-orphan", "orphan-host", "active",
        )
        assert repo.get_monitoring_hosts_by_tenant(tenant.id) == []


# --- SyncRun operations ---


class TestSyncRunOperations:
    @pytest.fixture
    def account(self, repo):
        tenant = repo.create_tenant("Sync Tenant")
        return repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Sync")

    def test_create_sync_run(self, repo, account):
        run = repo.create_sync_run("yandex_cloud", cloud_account_id=account.id)
        assert run.id is not None
        assert run.source == "yandex_cloud"
        assert run.status == "running"
        assert run.started_at is not None
        assert run.cloud_account_id == account.id

    def test_create_sync_run_no_account(self, repo):
        run = repo.create_sync_run("zabbix")
        assert run.id is not None
        assert run.cloud_account_id is None

    def test_update_sync_run_success(self, repo, account):
        run = repo.create_sync_run("yandex_cloud", cloud_account_id=account.id)
        updated = repo.update_sync_run(
            run.id,
            status="success",
            items_found=50,
            items_created=10,
            items_updated=5,
        )
        assert updated is not None
        assert updated.status == "success"
        assert updated.items_found == 50
        assert updated.items_created == 10
        assert updated.items_updated == 5
        assert updated.finished_at is not None
        assert updated.error_message is None

    def test_update_sync_run_failed(self, repo, account):
        run = repo.create_sync_run("yandex_cloud", cloud_account_id=account.id)
        updated = repo.update_sync_run(
            run.id,
            status="failed",
            error_message="Connection refused",
        )
        assert updated.status == "failed"
        assert updated.error_message == "Connection refused"
        assert updated.finished_at is not None

    def test_update_sync_run_not_found(self, repo):
        assert repo.update_sync_run(99999, "success") is None

    def test_get_latest_sync_runs(self, repo, account):
        for _ in range(5):
            run = repo.create_sync_run("yandex_cloud", cloud_account_id=account.id)
            repo.update_sync_run(run.id, "success")
        runs = repo.get_latest_sync_runs(limit=3)
        assert len(runs) == 3

    def test_get_latest_sync_runs_order(self, repo):
        r1 = repo.create_sync_run("yandex_cloud")
        r1.started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        r2 = repo.create_sync_run("vcloud")
        r2.started_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        r3 = repo.create_sync_run("zabbix")
        r3.started_at = datetime(2024, 12, 1, tzinfo=timezone.utc)
        repo.session.flush()

        runs = repo.get_latest_sync_runs(limit=10)
        sources = [r.source for r in runs]
        assert sources == ["zabbix", "vcloud", "yandex_cloud"]

    def test_get_latest_sync_runs_empty(self, repo):
        assert repo.get_latest_sync_runs() == []

    def test_get_latest_sync_runs_default_limit(self, repo):
        for i in range(15):
            repo.create_sync_run("yandex_cloud")
        runs = repo.get_latest_sync_runs()
        assert len(runs) == 10  # default limit

    # --- get_latest_sync_run_by_source ---

    def test_get_latest_sync_run_by_source_returns_most_recent(self, repo):
        r1 = repo.create_sync_run("netbox")
        r1.started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        r2 = repo.create_sync_run("netbox")
        r2.started_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        repo.session.flush()

        result = repo.get_latest_sync_run_by_source("netbox")
        assert result is not None
        assert result.id == r2.id

    def test_get_latest_sync_run_by_source_none_exists(self, repo):
        assert repo.get_latest_sync_run_by_source("netbox") is None

    def test_get_latest_sync_run_by_source_filters_by_source(self, repo):
        repo.create_sync_run("netbox")
        repo.create_sync_run("zabbix")
        repo.session.flush()

        result = repo.get_latest_sync_run_by_source("zabbix")
        assert result is not None
        assert result.source == "zabbix"

    def test_get_latest_sync_run_by_source_tenant_scoping(self, repo, account):
        """Tenant-scoped query returns runs for that tenant's accounts."""
        r1 = repo.create_sync_run("netbox", cloud_account_id=account.id)
        r1.started_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        repo.session.flush()

        tenant_id = account.tenant_id
        result = repo.get_latest_sync_run_by_source("netbox", tenant_id=tenant_id)
        assert result is not None
        assert result.id == r1.id

    def test_get_latest_sync_run_by_source_global_visible_with_tenant(self, repo, account):
        """Global runs (no cloud_account) are visible even with tenant filter."""
        r1 = repo.create_sync_run("zabbix")  # global, no account
        repo.session.flush()

        tenant_id = account.tenant_id
        result = repo.get_latest_sync_run_by_source("zabbix", tenant_id=tenant_id)
        assert result is not None
        assert result.id == r1.id
