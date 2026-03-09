"""Tests for NetBoxHost model, repository operations, and ingestion."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from infraverse.db.engine import create_engine, create_session_factory, init_db
from infraverse.db.models import NetBoxHost
from infraverse.db.repository import Repository
from infraverse.providers.base import VMInfo
from infraverse.sync.ingest import DataIngestor


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    factory = create_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def repo(session):
    return Repository(session)


# --- Repository: upsert_netbox_host ---


class TestUpsertNetBoxHost:
    def test_create_new_host(self, repo, session):
        host, created = repo.upsert_netbox_host(
            external_id="42",
            name="web-01",
            status="active",
            ip_addresses=["10.0.0.1"],
            cluster_name="prod-cluster",
            vcpus=4,
            memory_mb=8192,
        )
        session.commit()

        assert created is True
        assert host.external_id == "42"
        assert host.name == "web-01"
        assert host.status == "active"
        assert host.ip_addresses == ["10.0.0.1"]
        assert host.cluster_name == "prod-cluster"
        assert host.vcpus == 4
        assert host.memory_mb == 8192
        assert host.last_seen_at is not None

    def test_update_existing_host(self, repo, session):
        repo.upsert_netbox_host(
            external_id="42",
            name="web-01",
            status="active",
            ip_addresses=["10.0.0.1"],
        )
        session.commit()

        host, created = repo.upsert_netbox_host(
            external_id="42",
            name="web-01-renamed",
            status="offline",
            ip_addresses=["10.0.0.2"],
            vcpus=8,
        )
        session.commit()

        assert created is False
        assert host.name == "web-01-renamed"
        assert host.status == "offline"
        assert host.ip_addresses == ["10.0.0.2"]
        assert host.vcpus == 8


# --- Repository: list_netbox_hosts ---


class TestGetAllNetBoxHosts:
    def test_returns_empty_when_no_hosts(self, repo):
        assert repo.list_netbox_hosts() == []

    def test_returns_all_hosts_sorted(self, repo, session):
        repo.upsert_netbox_host(external_id="2", name="zz-host")
        repo.upsert_netbox_host(external_id="1", name="aa-host")
        session.commit()

        hosts = repo.list_netbox_hosts()
        assert len(hosts) == 2
        assert hosts[0].name == "aa-host"
        assert hosts[1].name == "zz-host"


# --- Repository: mark_netbox_hosts_stale ---


class TestMarkNetBoxHostsStale:
    def test_marks_old_hosts_offline(self, repo, session):
        repo.upsert_netbox_host(external_id="1", name="old-host", status="active")
        session.commit()

        # Mark anything not seen after "now" as stale
        future = datetime.now(timezone.utc) + timedelta(seconds=10)
        count = repo.mark_netbox_hosts_stale(future)
        session.commit()

        assert count == 1
        hosts = repo.list_netbox_hosts()
        assert hosts[0].status == "offline"

    def test_does_not_mark_recent_hosts(self, repo, session):
        repo.upsert_netbox_host(external_id="1", name="fresh-host", status="active")
        session.commit()

        # Use a cutoff in the past
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        count = repo.mark_netbox_hosts_stale(past)

        assert count == 0

    def test_marks_hosts_with_null_last_seen(self, repo, session):
        host = NetBoxHost(
            external_id="99", name="null-seen", status="active",
        )
        session.add(host)
        session.commit()

        future = datetime.now(timezone.utc) + timedelta(seconds=10)
        count = repo.mark_netbox_hosts_stale(future)
        assert count == 1


# --- DataIngestor: ingest_netbox_hosts ---


class TestIngestNetBoxHosts:
    def test_happy_path(self, session):
        ingestor = DataIngestor(session)
        mock_client = MagicMock()
        mock_client.fetch_all_vms.return_value = [
            VMInfo(
                name="nb-vm-1",
                id="100",
                status="active",
                ip_addresses=["10.0.0.1"],
                vcpus=2,
                memory_mb=4096,
                folder_name="cluster-a",
            ),
            VMInfo(
                name="nb-vm-2",
                id="101",
                status="offline",
                ip_addresses=[],
            ),
        ]

        count = ingestor.ingest_netbox_hosts(mock_client)

        assert count == 2
        repo = Repository(session)
        hosts = repo.list_netbox_hosts()
        assert len(hosts) == 2
        names = {h.name for h in hosts}
        assert names == {"nb-vm-1", "nb-vm-2"}

    def test_api_failure_records_failed_sync_run(self, session):
        ingestor = DataIngestor(session)
        mock_client = MagicMock()
        mock_client.fetch_all_vms.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError, match="API down"):
            ingestor.ingest_netbox_hosts(mock_client)

        # SyncRun should be marked as failed
        repo = Repository(session)
        runs = repo.get_latest_sync_runs(limit=1)
        assert len(runs) == 1
        assert runs[0].source == "netbox"
        assert runs[0].status == "failed"
        assert "API down" in runs[0].error_message

    def test_upsert_updates_existing(self, session):
        ingestor = DataIngestor(session)
        mock_client = MagicMock()

        # First ingestion
        mock_client.fetch_all_vms.return_value = [
            VMInfo(name="vm-1", id="100", status="active"),
        ]
        ingestor.ingest_netbox_hosts(mock_client)

        # Second ingestion with updated data
        mock_client.fetch_all_vms.return_value = [
            VMInfo(name="vm-1-renamed", id="100", status="offline"),
        ]
        ingestor.ingest_netbox_hosts(mock_client)

        repo = Repository(session)
        hosts = repo.list_netbox_hosts()
        assert len(hosts) == 1
        assert hosts[0].name == "vm-1-renamed"
        assert hosts[0].status == "offline"

    def test_resolves_tenant_name_to_tenant_id(self, session):
        """ingest_netbox_hosts maps VMInfo.tenant_name to NetBoxHost.tenant_id."""
        repo = Repository(session)
        tenant = repo.create_tenant("Acme Corp")
        session.commit()

        ingestor = DataIngestor(session)
        mock_client = MagicMock()
        mock_client.fetch_all_vms.return_value = [
            VMInfo(name="nb-vm-1", id="200", status="active", tenant_name="Acme Corp"),
            VMInfo(name="nb-vm-2", id="201", status="active", tenant_name="Unknown Corp"),
            VMInfo(name="nb-vm-3", id="202", status="active", tenant_name=""),
        ]
        ingestor.ingest_netbox_hosts(mock_client)

        hosts = {h.name: h for h in repo.list_netbox_hosts()}
        assert hosts["nb-vm-1"].tenant_id == tenant.id
        assert hosts["nb-vm-2"].tenant_id is None
        assert hosts["nb-vm-3"].tenant_id is None


# --- Repository: upsert_netbox_host with tenant_id ---


class TestUpsertNetBoxHostTenant:
    def test_create_with_tenant_id(self, repo, session):
        tenant = repo.create_tenant("Test Tenant")
        session.flush()
        host, created = repo.upsert_netbox_host(
            external_id="50",
            name="tenant-host",
            status="active",
            tenant_id=tenant.id,
        )
        session.commit()

        assert created is True
        assert host.tenant_id == tenant.id

    def test_update_sets_tenant_id(self, repo, session):
        repo.upsert_netbox_host(external_id="50", name="host-1")
        session.commit()

        tenant = repo.create_tenant("New Tenant")
        session.flush()
        host, created = repo.upsert_netbox_host(
            external_id="50",
            name="host-1",
            tenant_id=tenant.id,
        )
        session.commit()

        assert created is False
        assert host.tenant_id == tenant.id


# --- Repository: get_netbox_hosts_by_tenant ---


class TestGetNetBoxHostsByTenant:
    def test_returns_only_tenant_hosts(self, repo, session):
        t1 = repo.create_tenant("Tenant A")
        t2 = repo.create_tenant("Tenant B")
        session.flush()

        repo.upsert_netbox_host(external_id="1", name="a-host", tenant_id=t1.id)
        repo.upsert_netbox_host(external_id="2", name="b-host", tenant_id=t2.id)
        repo.upsert_netbox_host(external_id="3", name="no-tenant-host")
        session.commit()

        hosts = repo.get_netbox_hosts_by_tenant(t1.id)
        assert len(hosts) == 1
        assert hosts[0].name == "a-host"

    def test_returns_empty_for_unknown_tenant(self, repo, session):
        repo.upsert_netbox_host(external_id="1", name="some-host")
        session.commit()

        assert repo.get_netbox_hosts_by_tenant(9999) == []
