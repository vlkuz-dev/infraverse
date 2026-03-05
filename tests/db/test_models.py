"""Tests for database models, relationships, and engine initialization."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infraverse.db.models import (
    Base,
    Tenant,
    CloudAccount,
    VM,
    MonitoringHost,
    SyncRun,
)
from infraverse.db.engine import (
    create_engine as iv_create_engine,
    create_session_factory,
    init_db,
)


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine with all tables and FK enforcement."""
    from sqlalchemy import event

    eng = create_engine("sqlite:///:memory:")
    # Enable foreign key enforcement for SQLite
    event.listen(eng, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    """Create a database session for testing."""
    with Session(engine) as sess:
        yield sess


# --- Engine and init_db tests ---


class TestEngine:
    def test_create_engine_sqlite(self):
        eng = iv_create_engine("sqlite:///:memory:")
        assert eng is not None

    def test_create_session_factory(self):
        eng = iv_create_engine("sqlite:///:memory:")
        factory = create_session_factory(eng)
        sess = factory()
        assert isinstance(sess, Session)
        sess.close()

    def test_init_db_creates_tables(self):
        eng = iv_create_engine("sqlite:///:memory:")
        init_db(eng)
        inspector = inspect(eng)
        table_names = inspector.get_table_names()
        assert "tenants" in table_names
        assert "cloud_accounts" in table_names
        assert "vms" in table_names
        assert "monitoring_hosts" in table_names
        assert "sync_runs" in table_names

    def test_init_db_idempotent(self):
        eng = iv_create_engine("sqlite:///:memory:")
        init_db(eng)
        init_db(eng)
        inspector = inspect(eng)
        assert "tenants" in inspector.get_table_names()


# --- Tenant model tests ---


class TestTenantModel:
    def test_create_tenant(self, session):
        tenant = Tenant(name="Acme Corp", description="Test tenant")
        session.add(tenant)
        session.commit()
        assert tenant.id is not None
        assert tenant.name == "Acme Corp"
        assert tenant.description == "Test tenant"

    def test_tenant_timestamps(self, session):
        tenant = Tenant(name="Timestamp Corp")
        session.add(tenant)
        session.commit()
        assert tenant.created_at is not None
        assert tenant.updated_at is not None
        assert isinstance(tenant.created_at, datetime)

    def test_tenant_repr(self, session):
        tenant = Tenant(name="Repr Corp")
        session.add(tenant)
        session.commit()
        assert "Repr Corp" in repr(tenant)

    def test_tenant_nullable_description(self, session):
        tenant = Tenant(name="No Desc")
        session.add(tenant)
        session.commit()
        assert tenant.description is None

    def test_tenant_unique_name(self, session):
        session.add(Tenant(name="Unique"))
        session.commit()
        session.add(Tenant(name="Unique"))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_tenant_name_required(self, session):
        tenant = Tenant()
        session.add(tenant)
        with pytest.raises(IntegrityError):
            session.commit()


# --- CloudAccount model tests ---


class TestCloudAccountModel:
    def test_create_cloud_account(self, session):
        tenant = Tenant(name="CA Tenant")
        session.add(tenant)
        session.flush()

        account = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC Russia",
        )
        session.add(account)
        session.commit()
        assert account.id is not None
        assert account.provider_type == "yandex_cloud"
        assert account.name == "YC Russia"

    def test_cloud_account_default_config(self, session):
        tenant = Tenant(name="Default Config Tenant")
        session.add(tenant)
        session.flush()

        account = CloudAccount(
            tenant_id=tenant.id,
            provider_type="vcloud",
            name="vCloud Default",
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        assert account.config == {}

    def test_cloud_account_json_config(self, session):
        tenant = Tenant(name="JSON Config Tenant")
        session.add(tenant)
        session.flush()

        config = {"endpoint": "https://api.cloud.yandex.net", "region": "ru-central1"}
        account = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC With Config",
            config=config,
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        assert account.config["endpoint"] == "https://api.cloud.yandex.net"
        assert account.config["region"] == "ru-central1"

    def test_cloud_account_tenant_relationship(self, session):
        tenant = Tenant(name="Rel Tenant")
        session.add(tenant)
        session.flush()

        account = CloudAccount(
            tenant_id=tenant.id,
            provider_type="netbox",
            name="NetBox Prod",
        )
        session.add(account)
        session.commit()
        assert account.tenant.name == "Rel Tenant"
        assert len(tenant.cloud_accounts) == 1

    def test_cloud_account_requires_tenant(self, session):
        account = CloudAccount(
            tenant_id=99999,
            provider_type="yandex_cloud",
            name="Orphan",
        )
        session.add(account)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_cloud_account_repr(self, session):
        tenant = Tenant(name="Repr CA Tenant")
        session.add(tenant)
        session.flush()
        account = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC Repr",
        )
        session.add(account)
        session.commit()
        r = repr(account)
        assert "YC Repr" in r
        assert "yandex_cloud" in r


# --- VM model tests ---


class TestVMModel:
    @pytest.fixture
    def account(self, session):
        tenant = Tenant(name="VM Tenant")
        session.add(tenant)
        session.flush()
        acc = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC VMs",
        )
        session.add(acc)
        session.flush()
        return acc

    def test_create_vm(self, session, account):
        vm = VM(
            cloud_account_id=account.id,
            external_id="fhm12345",
            name="web-server-1",
            status="active",
            ip_addresses=["10.0.0.1", "192.168.1.1"],
            vcpus=4,
            memory_mb=8192,
        )
        session.add(vm)
        session.commit()
        assert vm.id is not None
        assert vm.name == "web-server-1"
        assert vm.status == "active"
        assert vm.ip_addresses == ["10.0.0.1", "192.168.1.1"]
        assert vm.vcpus == 4
        assert vm.memory_mb == 8192

    def test_vm_default_status(self, session, account):
        vm = VM(
            cloud_account_id=account.id,
            external_id="fhm-default",
            name="default-vm",
        )
        session.add(vm)
        session.commit()
        assert vm.status == "unknown"

    def test_vm_default_ip_addresses(self, session, account):
        vm = VM(
            cloud_account_id=account.id,
            external_id="fhm-noip",
            name="no-ip-vm",
        )
        session.add(vm)
        session.commit()
        session.refresh(vm)
        assert vm.ip_addresses == []

    def test_vm_nullable_fields(self, session, account):
        vm = VM(
            cloud_account_id=account.id,
            external_id="fhm-nullable",
            name="nullable-vm",
        )
        session.add(vm)
        session.commit()
        assert vm.vcpus is None
        assert vm.memory_mb is None
        assert vm.cloud_name is None
        assert vm.folder_name is None
        assert vm.last_seen_at is None

    def test_vm_cloud_account_relationship(self, session, account):
        vm = VM(
            cloud_account_id=account.id,
            external_id="fhm-rel",
            name="rel-vm",
        )
        session.add(vm)
        session.commit()
        assert vm.cloud_account.name == "YC VMs"
        assert len(account.vms) == 1

    def test_vm_unique_constraint(self, session, account):
        session.add(VM(
            cloud_account_id=account.id,
            external_id="fhm-dup",
            name="vm-1",
        ))
        session.commit()
        session.add(VM(
            cloud_account_id=account.id,
            external_id="fhm-dup",
            name="vm-2",
        ))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_vm_same_external_id_different_accounts(self, session):
        tenant = Tenant(name="Multi Account Tenant")
        session.add(tenant)
        session.flush()

        acc1 = CloudAccount(tenant_id=tenant.id, provider_type="yandex_cloud", name="YC1")
        acc2 = CloudAccount(tenant_id=tenant.id, provider_type="yandex_cloud", name="YC2")
        session.add_all([acc1, acc2])
        session.flush()

        vm1 = VM(cloud_account_id=acc1.id, external_id="same-id", name="vm-acc1")
        vm2 = VM(cloud_account_id=acc2.id, external_id="same-id", name="vm-acc2")
        session.add_all([vm1, vm2])
        session.commit()
        assert vm1.id != vm2.id

    def test_vm_repr(self, session, account):
        vm = VM(
            cloud_account_id=account.id,
            external_id="fhm-repr",
            name="repr-vm",
            status="active",
        )
        session.add(vm)
        session.commit()
        r = repr(vm)
        assert "repr-vm" in r
        assert "active" in r

    def test_vm_with_cloud_and_folder(self, session, account):
        vm = VM(
            cloud_account_id=account.id,
            external_id="fhm-cf",
            name="cloud-folder-vm",
            cloud_name="my-cloud",
            folder_name="my-folder",
        )
        session.add(vm)
        session.commit()
        assert vm.cloud_name == "my-cloud"
        assert vm.folder_name == "my-folder"


# --- MonitoringHost model tests ---


class TestMonitoringHostModel:
    def test_create_monitoring_host(self, session):
        host = MonitoringHost(
            source="zabbix",
            external_id="zbx-10001",
            name="monitor-server-1",
            status="active",
            ip_addresses=["10.0.0.5"],
        )
        session.add(host)
        session.commit()
        assert host.id is not None
        assert host.source == "zabbix"
        assert host.name == "monitor-server-1"

    def test_monitoring_host_unique_constraint(self, session):
        session.add(MonitoringHost(
            source="zabbix",
            external_id="zbx-dup",
            name="host-1",
        ))
        session.commit()
        session.add(MonitoringHost(
            source="zabbix",
            external_id="zbx-dup",
            name="host-2",
        ))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_monitoring_host_same_id_different_source(self, session):
        h1 = MonitoringHost(source="zabbix", external_id="same-id", name="h1")
        h2 = MonitoringHost(source="prometheus", external_id="same-id", name="h2")
        session.add_all([h1, h2])
        session.commit()
        assert h1.id != h2.id

    def test_monitoring_host_default_ip(self, session):
        host = MonitoringHost(
            source="zabbix",
            external_id="zbx-noip",
            name="no-ip-host",
        )
        session.add(host)
        session.commit()
        session.refresh(host)
        assert host.ip_addresses == []

    def test_monitoring_host_repr(self, session):
        host = MonitoringHost(
            source="zabbix",
            external_id="zbx-repr",
            name="repr-host",
        )
        session.add(host)
        session.commit()
        r = repr(host)
        assert "repr-host" in r
        assert "zabbix" in r


# --- SyncRun model tests ---


class TestSyncRunModel:
    @pytest.fixture
    def account(self, session):
        tenant = Tenant(name="Sync Tenant")
        session.add(tenant)
        session.flush()
        acc = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC Sync",
        )
        session.add(acc)
        session.flush()
        return acc

    def test_create_sync_run(self, session, account):
        run = SyncRun(
            cloud_account_id=account.id,
            source="yandex_cloud",
            status="running",
        )
        session.add(run)
        session.commit()
        assert run.id is not None
        assert run.source == "yandex_cloud"
        assert run.status == "running"
        assert run.started_at is not None

    def test_sync_run_defaults(self, session, account):
        run = SyncRun(
            cloud_account_id=account.id,
            source="yandex_cloud",
        )
        session.add(run)
        session.commit()
        assert run.status == "running"
        assert run.items_found == 0
        assert run.items_created == 0
        assert run.items_updated == 0
        assert run.error_message is None
        assert run.finished_at is None

    def test_sync_run_nullable_account(self, session):
        run = SyncRun(
            source="zabbix",
            status="success",
        )
        session.add(run)
        session.commit()
        assert run.cloud_account_id is None
        assert run.cloud_account is None

    def test_sync_run_with_results(self, session, account):
        now = datetime.now(timezone.utc)
        run = SyncRun(
            cloud_account_id=account.id,
            source="vcloud",
            status="success",
            items_found=50,
            items_created=10,
            items_updated=5,
            finished_at=now,
        )
        session.add(run)
        session.commit()
        assert run.items_found == 50
        assert run.items_created == 10
        assert run.items_updated == 5
        # SQLite strips timezone info, so compare the naive parts
        assert run.finished_at.replace(tzinfo=None) == now.replace(tzinfo=None)

    def test_sync_run_with_error(self, session, account):
        run = SyncRun(
            cloud_account_id=account.id,
            source="yandex_cloud",
            status="failed",
            error_message="Connection timeout",
        )
        session.add(run)
        session.commit()
        assert run.error_message == "Connection timeout"

    def test_sync_run_account_relationship(self, session, account):
        run = SyncRun(
            cloud_account_id=account.id,
            source="yandex_cloud",
        )
        session.add(run)
        session.commit()
        assert run.cloud_account.name == "YC Sync"
        assert len(account.sync_runs) == 1

    def test_sync_run_repr(self, session):
        run = SyncRun(source="zabbix", status="success")
        session.add(run)
        session.commit()
        r = repr(run)
        assert "zabbix" in r
        assert "success" in r


# --- Cascade and relationship tests ---


class TestRelationships:
    def test_tenant_cascade_delete_accounts(self, session):
        tenant = Tenant(name="Cascade Tenant")
        session.add(tenant)
        session.flush()

        acc = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="Cascade Account",
        )
        session.add(acc)
        session.commit()

        session.delete(tenant)
        session.commit()

        assert session.query(CloudAccount).count() == 0

    def test_account_cascade_delete_vms(self, session):
        tenant = Tenant(name="VM Cascade Tenant")
        session.add(tenant)
        session.flush()

        acc = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="VM Cascade Acc",
        )
        session.add(acc)
        session.flush()

        vm = VM(
            cloud_account_id=acc.id,
            external_id="cascade-vm",
            name="will-be-deleted",
        )
        session.add(vm)
        session.commit()

        session.delete(acc)
        session.commit()
        assert session.query(VM).count() == 0

    def test_tenant_cascade_deletes_vms_through_account(self, session):
        tenant = Tenant(name="Deep Cascade Tenant")
        session.add(tenant)
        session.flush()

        acc = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="Deep Cascade Acc",
        )
        session.add(acc)
        session.flush()

        vm = VM(
            cloud_account_id=acc.id,
            external_id="deep-vm",
            name="deep-delete",
        )
        run = SyncRun(
            cloud_account_id=acc.id,
            source="yandex_cloud",
        )
        session.add_all([vm, run])
        session.commit()

        session.delete(tenant)
        session.commit()
        assert session.query(VM).count() == 0
        assert session.query(SyncRun).count() == 0
        assert session.query(CloudAccount).count() == 0

    def test_multiple_accounts_per_tenant(self, session):
        tenant = Tenant(name="Multi Account")
        session.add(tenant)
        session.flush()

        for i, ptype in enumerate(["yandex_cloud", "vcloud", "netbox"]):
            acc = CloudAccount(
                tenant_id=tenant.id,
                provider_type=ptype,
                name=f"Account-{i}",
            )
            session.add(acc)
        session.commit()
        assert len(tenant.cloud_accounts) == 3

    def test_multiple_vms_per_account(self, session):
        tenant = Tenant(name="Multi VM Tenant")
        session.add(tenant)
        session.flush()

        acc = CloudAccount(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="Multi VM Acc",
        )
        session.add(acc)
        session.flush()

        for i in range(5):
            vm = VM(
                cloud_account_id=acc.id,
                external_id=f"vm-{i}",
                name=f"server-{i}",
                status="active",
            )
            session.add(vm)
        session.commit()
        assert len(acc.vms) == 5
