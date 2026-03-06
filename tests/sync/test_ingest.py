"""Tests for the DataIngestor - provider to DB ingestion pipeline."""

import pytest
from unittest.mock import MagicMock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from infraverse.db.models import Base, VM, MonitoringHost, SyncRun
from infraverse.db.repository import Repository
from infraverse.providers.base import VMInfo
from infraverse.providers.zabbix import ZabbixHost
from infraverse.sync.ingest import DataIngestor


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def repo(session):
    return Repository(session)


@pytest.fixture
def ingestor(session):
    return DataIngestor(session)


@pytest.fixture
def tenant_and_account(repo, session):
    """Create a tenant and cloud account for testing."""
    tenant = repo.create_tenant("Test Corp")
    account = repo.create_cloud_account(
        tenant_id=tenant.id,
        provider_type="yandex_cloud",
        name="YC Russia",
    )
    session.commit()
    return tenant, account


def _make_mock_provider(vms: list[VMInfo] | None = None, error: Exception | None = None):
    """Create a mock CloudProvider."""
    provider = MagicMock()
    provider.get_provider_name.return_value = "yandex_cloud"
    if error:
        provider.fetch_vms.side_effect = error
    else:
        provider.fetch_vms.return_value = vms or []
    return provider


def _make_mock_zabbix(hosts: list[ZabbixHost] | None = None, error: Exception | None = None):
    """Create a mock ZabbixClient."""
    client = MagicMock()
    if error:
        client.fetch_hosts.side_effect = error
    else:
        client.fetch_hosts.return_value = hosts or []
    return client


# --- ingest_cloud_vms tests ---


class TestIngestCloudVms:
    def test_ingest_empty_provider(self, ingestor, tenant_and_account, session):
        _, account = tenant_and_account
        provider = _make_mock_provider(vms=[])

        count = ingestor.ingest_cloud_vms(account, provider)

        assert count == 0
        assert session.query(VM).count() == 0
        run = session.query(SyncRun).one()
        assert run.status == "success"
        assert run.items_found == 0
        assert run.cloud_account_id == account.id

    def test_ingest_creates_new_vms(self, ingestor, tenant_and_account, session):
        _, account = tenant_and_account
        vms = [
            VMInfo(name="vm-1", id="ext-1", status="active", ip_addresses=["10.0.0.1"],
                   vcpus=2, memory_mb=4096, cloud_name="cloud-1", folder_name="folder-1"),
            VMInfo(name="vm-2", id="ext-2", status="offline", ip_addresses=["10.0.0.2"],
                   vcpus=4, memory_mb=8192),
        ]
        provider = _make_mock_provider(vms=vms)

        count = ingestor.ingest_cloud_vms(account, provider)

        assert count == 2
        db_vms = session.query(VM).order_by(VM.name).all()
        assert len(db_vms) == 2
        assert db_vms[0].name == "vm-1"
        assert db_vms[0].external_id == "ext-1"
        assert db_vms[0].status == "active"
        assert db_vms[0].ip_addresses == ["10.0.0.1"]
        assert db_vms[0].vcpus == 2
        assert db_vms[0].memory_mb == 4096
        assert db_vms[0].cloud_name == "cloud-1"
        assert db_vms[0].folder_name == "folder-1"
        assert db_vms[1].name == "vm-2"
        assert db_vms[1].status == "offline"

        run = session.query(SyncRun).one()
        assert run.status == "success"
        assert run.items_found == 2
        assert run.items_created == 2
        assert run.items_updated == 0

    def test_ingest_updates_existing_vms(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        # Pre-create a VM
        repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="ext-1",
            name="old-name",
            status="active",
        )
        session.commit()

        # Ingest with updated data
        vms = [VMInfo(name="new-name", id="ext-1", status="offline", ip_addresses=["10.0.0.5"])]
        provider = _make_mock_provider(vms=vms)

        count = ingestor.ingest_cloud_vms(account, provider)

        assert count == 1
        db_vm = session.query(VM).one()
        assert db_vm.name == "new-name"
        assert db_vm.status == "offline"
        assert db_vm.ip_addresses == ["10.0.0.5"]

        run = session.query(SyncRun).one()
        assert run.items_found == 1
        assert run.items_created == 0
        assert run.items_updated == 1

    def test_ingest_marks_stale_vms(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        # Pre-create a VM that won't be in the new fetch
        repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="old-vm",
            name="stale-vm",
            status="active",
        )
        session.commit()

        # Ingest with different VM (old one missing)
        vms = [VMInfo(name="fresh-vm", id="fresh-1", status="active")]
        provider = _make_mock_provider(vms=vms)

        ingestor.ingest_cloud_vms(account, provider)

        stale = session.query(VM).filter_by(external_id="old-vm").one()
        assert stale.status == "offline"

        fresh = session.query(VM).filter_by(external_id="fresh-1").one()
        assert fresh.status == "active"

    def test_ingest_creates_sync_run(self, ingestor, tenant_and_account, session):
        _, account = tenant_and_account
        provider = _make_mock_provider(vms=[VMInfo(name="vm", id="1", status="active")])

        ingestor.ingest_cloud_vms(account, provider)

        run = session.query(SyncRun).one()
        assert run.source == "yandex_cloud"
        assert run.cloud_account_id == account.id
        assert run.status == "success"
        assert run.finished_at is not None
        assert run.started_at is not None

    def test_ingest_provider_error_records_failed_sync_run(
        self, ingestor, tenant_and_account, session
    ):
        _, account = tenant_and_account
        provider = _make_mock_provider(error=RuntimeError("API timeout"))

        with pytest.raises(RuntimeError, match="API timeout"):
            ingestor.ingest_cloud_vms(account, provider)

        run = session.query(SyncRun).one()
        assert run.status == "failed"
        assert "API timeout" in run.error_message
        assert run.finished_at is not None
        assert session.query(VM).count() == 0

    def test_ingest_mixed_create_and_update(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        repo.upsert_vm(cloud_account_id=account.id, external_id="existing", name="old", status="active")
        session.commit()

        vms = [
            VMInfo(name="updated", id="existing", status="active"),
            VMInfo(name="brand-new", id="new-1", status="active"),
        ]
        provider = _make_mock_provider(vms=vms)

        ingestor.ingest_cloud_vms(account, provider)

        run = session.query(SyncRun).one()
        assert run.items_created == 1
        assert run.items_updated == 1
        assert run.items_found == 2


# --- ingest_monitoring_hosts tests ---


class TestIngestMonitoringHosts:
    def test_ingest_empty_zabbix(self, ingestor, session):
        zabbix = _make_mock_zabbix(hosts=[])

        count = ingestor.ingest_monitoring_hosts(zabbix)

        assert count == 0
        assert session.query(MonitoringHost).count() == 0
        run = session.query(SyncRun).one()
        assert run.status == "success"
        assert run.source == "zabbix"

    def test_ingest_zabbix_hosts(self, ingestor, session):
        hosts = [
            ZabbixHost(name="web-1", hostid="101", status="active", ip_addresses=["10.0.0.1"]),
            ZabbixHost(name="db-1", hostid="102", status="offline", ip_addresses=["10.0.0.2"]),
        ]
        zabbix = _make_mock_zabbix(hosts=hosts)

        count = ingestor.ingest_monitoring_hosts(zabbix)

        assert count == 2
        db_hosts = session.query(MonitoringHost).order_by(MonitoringHost.name).all()
        assert len(db_hosts) == 2
        assert db_hosts[0].name == "db-1"
        assert db_hosts[0].external_id == "102"
        assert db_hosts[0].source == "zabbix"
        assert db_hosts[1].name == "web-1"
        assert db_hosts[1].ip_addresses == ["10.0.0.1"]

        run = session.query(SyncRun).one()
        assert run.status == "success"
        assert run.items_found == 2
        assert run.items_created == 2
        assert run.items_updated == 0

    def test_ingest_zabbix_updates_existing(self, ingestor, repo, session):
        repo.upsert_monitoring_host(
            source="zabbix", external_id="101", name="old-name", status="active",
        )
        session.commit()

        hosts = [ZabbixHost(name="new-name", hostid="101", status="offline", ip_addresses=["10.0.0.5"])]
        zabbix = _make_mock_zabbix(hosts=hosts)

        count = ingestor.ingest_monitoring_hosts(zabbix)

        assert count == 1
        db_host = session.query(MonitoringHost).one()
        assert db_host.name == "new-name"
        assert db_host.status == "offline"

        run = session.query(SyncRun).one()
        assert run.items_found == 1
        assert run.items_created == 0
        assert run.items_updated == 1

    def test_ingest_marks_stale_monitoring_hosts(self, ingestor, repo, session):
        # Pre-create a host that won't be in the new fetch
        repo.upsert_monitoring_host(
            source="zabbix", external_id="old-host", name="stale-host", status="active",
        )
        session.commit()

        # Ingest with different host (old one missing)
        hosts = [ZabbixHost(name="fresh-host", hostid="fresh-1", status="active")]
        zabbix = _make_mock_zabbix(hosts=hosts)

        ingestor.ingest_monitoring_hosts(zabbix)

        stale = session.query(MonitoringHost).filter_by(external_id="old-host").one()
        assert stale.status == "offline"

        fresh = session.query(MonitoringHost).filter_by(external_id="fresh-1").one()
        assert fresh.status == "active"

    def test_ingest_zabbix_error_records_failed_run(self, ingestor, session):
        zabbix = _make_mock_zabbix(error=RuntimeError("Zabbix unreachable"))

        with pytest.raises(RuntimeError, match="Zabbix unreachable"):
            ingestor.ingest_monitoring_hosts(zabbix)

        run = session.query(SyncRun).one()
        assert run.status == "failed"
        assert "Zabbix unreachable" in run.error_message


# --- ingest_all tests ---


class TestIngestAll:
    def test_ingest_all_success(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        # Create a second account
        account2 = repo.create_cloud_account(
            tenant_id=account.tenant_id,
            provider_type="vcloud",
            name="vCloud DC",
        )
        session.commit()

        provider1 = _make_mock_provider(vms=[VMInfo(name="yc-vm", id="y1", status="active")])
        provider2 = _make_mock_provider(vms=[VMInfo(name="vc-vm", id="v1", status="active")])
        zabbix = _make_mock_zabbix(hosts=[ZabbixHost(name="z-host", hostid="z1", status="active")])

        results = ingestor.ingest_all(
            providers={account.id: provider1, account2.id: provider2},
            zabbix_client=zabbix,
        )

        assert results["YC Russia"] == "success"
        assert results["vCloud DC"] == "success"
        assert results["zabbix"] == "success"
        assert session.query(VM).count() == 2
        assert session.query(MonitoringHost).count() == 1

    def test_ingest_all_without_zabbix(self, ingestor, tenant_and_account, session):
        _, account = tenant_and_account
        provider = _make_mock_provider(vms=[VMInfo(name="vm", id="1", status="active")])

        results = ingestor.ingest_all(providers={account.id: provider})

        assert results["YC Russia"] == "success"
        assert "zabbix" not in results
        assert session.query(VM).count() == 1

    def test_ingest_all_provider_failure_continues(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        account2 = repo.create_cloud_account(
            tenant_id=account.tenant_id,
            provider_type="vcloud",
            name="vCloud DC",
        )
        session.commit()

        failing_provider = _make_mock_provider(error=ConnectionError("network down"))
        working_provider = _make_mock_provider(vms=[VMInfo(name="ok-vm", id="ok1", status="active")])

        results = ingestor.ingest_all(
            providers={account.id: failing_provider, account2.id: working_provider},
        )

        assert "error:" in results["YC Russia"]
        assert "network down" in results["YC Russia"]
        assert results["vCloud DC"] == "success"
        # Working provider's VMs still got ingested
        assert session.query(VM).count() == 1

    def test_ingest_all_zabbix_failure_continues(self, ingestor, tenant_and_account, session):
        _, account = tenant_and_account
        provider = _make_mock_provider(vms=[VMInfo(name="vm", id="1", status="active")])
        zabbix = _make_mock_zabbix(error=RuntimeError("auth failed"))

        results = ingestor.ingest_all(
            providers={account.id: provider},
            zabbix_client=zabbix,
        )

        assert results["YC Russia"] == "success"
        assert "error:" in results["zabbix"]
        assert session.query(VM).count() == 1

    def test_ingest_all_missing_account(self, ingestor, session):
        provider = _make_mock_provider(vms=[])

        results = ingestor.ingest_all(providers={999: provider})

        assert results["account_999"] == "error: account not found"

    def test_ingest_all_empty(self, ingestor, session):
        results = ingestor.ingest_all(providers={})

        assert results == {}

    def test_ingest_all_both_fail(self, ingestor, tenant_and_account, session):
        _, account = tenant_and_account
        failing_provider = _make_mock_provider(error=RuntimeError("cloud dead"))
        failing_zabbix = _make_mock_zabbix(error=RuntimeError("zabbix dead"))

        results = ingestor.ingest_all(
            providers={account.id: failing_provider},
            zabbix_client=failing_zabbix,
        )

        assert "error:" in results["YC Russia"]
        assert "error:" in results["zabbix"]
        # Both SyncRuns should be recorded as failed
        runs = session.query(SyncRun).all()
        assert len(runs) == 2
        assert all(r.status == "failed" for r in runs)
