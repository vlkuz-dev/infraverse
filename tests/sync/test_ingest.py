"""Tests for the DataIngestor - provider to DB ingestion pipeline."""

import pytest
from unittest.mock import MagicMock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from infraverse.db.models import Base, VM, MonitoringHost, SyncRun
from infraverse.db.repository import Repository
from infraverse.providers.base import VMInfo
from infraverse.providers.zabbix import ZabbixHost
from infraverse.config_file import MonitoringExclusionRule
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


def _make_mock_zabbix(
    name_results: dict[str, ZabbixHost | None] | None = None,
    ip_results: dict[str, ZabbixHost | None] | None = None,
    error: Exception | None = None,
):
    """Create a mock ZabbixClient with bulk fetch and per-VM search methods."""
    client = MagicMock()
    client.last_fetch_truncated = False
    if error:
        client.fetch_hosts.side_effect = error
        client.search_host_by_name.side_effect = error
    else:
        name_map = name_results or {}
        ip_map = ip_results or {}
        # Bulk fetch returns all unique hosts for local lookup
        all_hosts = list({id(h): h for h in [*name_map.values(), *ip_map.values()] if h is not None}.values())
        client.fetch_hosts.return_value = all_hosts
        # Per-VM fallback methods (used when bulk fetch fails)
        client.search_host_by_name.side_effect = lambda name: name_map.get(name)
        client.search_host_by_ip.side_effect = lambda ip: ip_map.get(ip)
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


# --- ingest_monitoring_hosts tests (per-VM monitoring check) ---


class TestIngestMonitoringHosts:
    def test_ingest_no_vms(self, ingestor, session):
        """No VMs to check -> 0 found, sync run success."""
        zabbix = _make_mock_zabbix()

        count = ingestor.ingest_monitoring_hosts([], zabbix)

        assert count == 0
        assert session.query(MonitoringHost).count() == 0
        run = session.query(SyncRun).one()
        assert run.status == "success"
        assert run.source == "zabbix"

    def test_ingest_vm_found_by_name(self, ingestor, tenant_and_account, repo, session):
        """VM found by name -> MonitoringHost created with cloud_account_id."""
        _, account = tenant_and_account
        vm, _ = repo.upsert_vm(
            cloud_account_id=account.id, external_id="ext-1",
            name="web-1", status="active", ip_addresses=["10.0.0.1"],
        )
        session.commit()

        zabbix_host = ZabbixHost(name="web-1", hostid="z101", status="active", ip_addresses=["10.0.0.1"])
        zabbix = _make_mock_zabbix(name_results={"web-1": zabbix_host})

        count = ingestor.ingest_monitoring_hosts([vm], zabbix)

        assert count == 1
        db_host = session.query(MonitoringHost).one()
        assert db_host.name == "web-1"
        assert db_host.external_id == "z101"
        assert db_host.source == "zabbix"
        assert db_host.cloud_account_id == account.id
        assert db_host.ip_addresses == ["10.0.0.1"]

    def test_ingest_vm_found_by_ip_fallback(self, ingestor, tenant_and_account, repo, session):
        """VM not found by name but found by IP -> MonitoringHost stores VM name (not Zabbix name)."""
        _, account = tenant_and_account
        vm, _ = repo.upsert_vm(
            cloud_account_id=account.id, external_id="ext-2",
            name="web-2", status="active", ip_addresses=["10.0.0.5"],
        )
        session.commit()

        zabbix_host = ZabbixHost(name="web-2-zabbix", hostid="z102", status="active", ip_addresses=["10.0.0.5"])
        zabbix = _make_mock_zabbix(ip_results={"10.0.0.5": zabbix_host})

        count = ingestor.ingest_monitoring_hosts([vm], zabbix)

        assert count == 1
        db_host = session.query(MonitoringHost).one()
        assert db_host.name == "web-2"
        assert db_host.external_id == "z102"
        assert db_host.cloud_account_id == account.id

    def test_ingest_vm_not_found(self, ingestor, tenant_and_account, repo, session):
        """VM not found in Zabbix -> no MonitoringHost created."""
        _, account = tenant_and_account
        vm, _ = repo.upsert_vm(
            cloud_account_id=account.id, external_id="ext-3",
            name="unknown-vm", status="active",
        )
        session.commit()

        zabbix = _make_mock_zabbix()

        count = ingestor.ingest_monitoring_hosts([vm], zabbix)

        assert count == 0
        assert session.query(MonitoringHost).count() == 0

    def test_ingest_mixed_found_and_not_found(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        vm1, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="e1", name="found-vm", status="active")
        vm2, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="e2", name="missing-vm", status="active")
        session.commit()

        host = ZabbixHost(name="found-vm", hostid="z1", status="active")
        zabbix = _make_mock_zabbix(name_results={"found-vm": host})

        count = ingestor.ingest_monitoring_hosts([vm1, vm2], zabbix)

        assert count == 1
        assert session.query(MonitoringHost).count() == 1
        db_host = session.query(MonitoringHost).one()
        assert db_host.name == "found-vm"

        run = session.query(SyncRun).one()
        assert run.items_found == 1
        assert run.items_created == 1

    def test_ingest_stores_cloud_account_id(self, ingestor, tenant_and_account, repo, session):
        """MonitoringHost records get cloud_account_id from their source VM."""
        tenant, account = tenant_and_account
        account2 = repo.create_cloud_account(
            tenant_id=tenant.id, provider_type="vcloud", name="vCloud",
        )
        session.commit()

        vm1, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="y1", name="yc-vm", status="active")
        vm2, _ = repo.upsert_vm(cloud_account_id=account2.id, external_id="v1", name="vc-vm", status="active")
        session.commit()

        h1 = ZabbixHost(name="yc-vm", hostid="z1", status="active")
        h2 = ZabbixHost(name="vc-vm", hostid="z2", status="active")
        zabbix = _make_mock_zabbix(name_results={"yc-vm": h1, "vc-vm": h2})

        count = ingestor.ingest_monitoring_hosts([vm1, vm2], zabbix)

        assert count == 2
        hosts = session.query(MonitoringHost).order_by(MonitoringHost.name).all()
        assert hosts[0].cloud_account_id == account2.id  # vc-vm -> vCloud account
        assert hosts[1].cloud_account_id == account.id    # yc-vm -> YC account

    def test_ingest_updates_existing_monitoring_host(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        repo.upsert_monitoring_host(
            source="zabbix", external_id="z101", name="old-name", status="active",
        )
        session.commit()

        vm, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="ext-1", name="web-1", status="active")
        session.commit()

        host = ZabbixHost(name="web-1", hostid="z101", status="offline", ip_addresses=["10.0.0.5"])
        zabbix = _make_mock_zabbix(name_results={"web-1": host})

        count = ingestor.ingest_monitoring_hosts([vm], zabbix)

        assert count == 1
        db_host = session.query(MonitoringHost).one()
        assert db_host.name == "web-1"  # stores VM name, not Zabbix host name
        assert db_host.status == "offline"
        assert db_host.cloud_account_id == account.id

        run = session.query(SyncRun).one()
        assert run.items_updated == 1
        assert run.items_created == 0

    def test_ingest_marks_stale_monitoring_hosts(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        repo.upsert_monitoring_host(
            source="zabbix", external_id="old-host", name="stale-host", status="active",
            cloud_account_id=account.id,
        )
        session.commit()

        vm, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="ext-1", name="fresh-vm", status="active")
        session.commit()

        host = ZabbixHost(name="fresh-vm", hostid="fresh-z", status="active")
        zabbix = _make_mock_zabbix(name_results={"fresh-vm": host})

        ingestor.ingest_monitoring_hosts([vm], zabbix)

        stale = session.query(MonitoringHost).filter_by(external_id="old-host").one()
        assert stale.status == "offline"

        fresh = session.query(MonitoringHost).filter_by(external_id="fresh-z").one()
        assert fresh.status == "active"

    def test_ingest_zabbix_per_vm_error_isolated(self, ingestor, tenant_and_account, repo, session):
        """Per-VM Zabbix errors are isolated; batch still succeeds with found=0."""
        _, account = tenant_and_account
        vm, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="ext-1", name="vm-1", status="active")
        session.commit()

        zabbix = _make_mock_zabbix(error=RuntimeError("Zabbix unreachable"))

        count = ingestor.ingest_monitoring_hosts([vm], zabbix)

        assert count == 0
        run = session.query(SyncRun).one()
        assert run.status == "success"
        assert run.items_found == 0

    def test_sync_run_records_correct_counts(self, ingestor, tenant_and_account, repo, session):
        _, account = tenant_and_account
        vm1, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="e1", name="vm-1", status="active")
        vm2, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="e2", name="vm-2", status="active")
        vm3, _ = repo.upsert_vm(cloud_account_id=account.id, external_id="e3", name="vm-3", status="active")
        session.commit()

        h1 = ZabbixHost(name="vm-1", hostid="z1", status="active")
        h2 = ZabbixHost(name="vm-2", hostid="z2", status="active")
        zabbix = _make_mock_zabbix(name_results={"vm-1": h1, "vm-2": h2})

        count = ingestor.ingest_monitoring_hosts([vm1, vm2, vm3], zabbix)

        assert count == 2
        run = session.query(SyncRun).one()
        assert run.status == "success"
        assert run.items_found == 2
        assert run.items_created == 2
        assert run.items_updated == 0


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
        # Per-VM monitoring: yc-vm found, vc-vm not found -> 1 MonitoringHost
        z_host = ZabbixHost(name="yc-vm", hostid="z1", status="active")
        zabbix = _make_mock_zabbix(name_results={"yc-vm": z_host})

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

    def test_ingest_all_zabbix_per_vm_error_isolated(self, ingestor, tenant_and_account, session):
        """Per-VM Zabbix errors are isolated; cloud ingest and zabbix batch both succeed."""
        _, account = tenant_and_account
        provider = _make_mock_provider(vms=[VMInfo(name="vm", id="1", status="active")])
        zabbix = _make_mock_zabbix(error=RuntimeError("auth failed"))

        results = ingestor.ingest_all(
            providers={account.id: provider},
            zabbix_client=zabbix,
        )

        assert results["YC Russia"] == "success"
        assert results["zabbix"] == "success"
        assert session.query(VM).count() == 1

    def test_ingest_all_missing_account(self, ingestor, session):
        provider = _make_mock_provider(vms=[])

        results = ingestor.ingest_all(providers={999: provider})

        assert results["account_999"] == "error: account not found"

    def test_ingest_all_empty(self, ingestor, session):
        results = ingestor.ingest_all(providers={})

        assert results == {}

    def test_ingest_all_cloud_fails_zabbix_skipped(self, ingestor, tenant_and_account, repo, session):
        """When cloud ingest fails, no VMs are available for monitoring check."""
        _, account = tenant_and_account

        failing_provider = _make_mock_provider(error=RuntimeError("cloud dead"))
        failing_zabbix = _make_mock_zabbix(error=RuntimeError("zabbix dead"))

        results = ingestor.ingest_all(
            providers={account.id: failing_provider},
            zabbix_client=failing_zabbix,
        )

        assert "error:" in results["YC Russia"]
        # Zabbix not in results: no VMs from active accounts -> monitoring skipped
        assert "zabbix" not in results
        runs = session.query(SyncRun).all()
        assert len(runs) == 1
        assert runs[0].status == "failed"

    def test_ingest_all_cloud_then_monitoring(self, ingestor, tenant_and_account, session):
        """Full flow: ingest cloud VMs, then check monitoring for those VMs."""
        _, account = tenant_and_account
        provider = _make_mock_provider(vms=[
            VMInfo(name="web-1", id="y1", status="active", ip_addresses=["10.0.0.1"]),
            VMInfo(name="db-1", id="y2", status="active", ip_addresses=["10.0.0.2"]),
        ])

        h1 = ZabbixHost(name="web-1", hostid="z1", status="active", ip_addresses=["10.0.0.1"])
        zabbix = _make_mock_zabbix(name_results={"web-1": h1})

        results = ingestor.ingest_all(
            providers={account.id: provider},
            zabbix_client=zabbix,
        )

        assert results["YC Russia"] == "success"
        assert results["zabbix"] == "success"
        assert session.query(VM).count() == 2
        assert session.query(MonitoringHost).count() == 1

        # MonitoringHost should be linked to the cloud account
        mon_host = session.query(MonitoringHost).one()
        assert mon_host.name == "web-1"
        assert mon_host.cloud_account_id == account.id


# --- exclusion rules tests ---


class TestIngestExclusionRules:
    @pytest.fixture
    def tenant_and_account(self, repo, session):
        tenant = repo.create_tenant("Exempt Corp")
        account = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Exempt")
        session.commit()
        return tenant, account

    def test_ingest_sets_exempt_flag(self, session, tenant_and_account):
        """VM matching a name_pattern rule gets monitoring_exempt=True in DB."""
        _, account = tenant_and_account
        rules = [MonitoringExclusionRule(name_pattern="test-*", reason="test VMs excluded")]
        ingestor = DataIngestor(session, exclusion_rules=rules)

        provider = _make_mock_provider(vms=[
            VMInfo(name="test-vm-1", id="ext-1", status="active"),
        ])

        ingestor.ingest_cloud_vms(account, provider)

        vm = session.query(VM).one()
        assert vm.monitoring_exempt is True
        assert vm.monitoring_exempt_reason == "test VMs excluded"

    def test_ingest_non_matching_vm_not_exempt(self, session, tenant_and_account):
        """VM not matching any rule stays exempt=False."""
        _, account = tenant_and_account
        rules = [MonitoringExclusionRule(name_pattern="test-*", reason="test VMs excluded")]
        ingestor = DataIngestor(session, exclusion_rules=rules)

        provider = _make_mock_provider(vms=[
            VMInfo(name="prod-web-1", id="ext-1", status="active"),
        ])

        ingestor.ingest_cloud_vms(account, provider)

        vm = session.query(VM).one()
        assert vm.monitoring_exempt is False
        assert vm.monitoring_exempt_reason is None

    def test_exempt_vms_skipped_for_monitoring(self, session, tenant_and_account):
        """In ingest_all, exempt VMs are not passed to monitoring check."""
        _, account = tenant_and_account
        rules = [MonitoringExclusionRule(name_pattern="test-*", reason="test VMs excluded")]
        ingestor = DataIngestor(session, exclusion_rules=rules)

        provider = _make_mock_provider(vms=[
            VMInfo(name="test-vm-1", id="ext-1", status="active"),
            VMInfo(name="prod-vm-1", id="ext-2", status="active", ip_addresses=["10.0.0.1"]),
        ])

        # Zabbix finds prod-vm-1 by name; test-vm-1 should never be queried
        z_host = ZabbixHost(name="prod-vm-1", hostid="z1", status="active", ip_addresses=["10.0.0.1"])
        zabbix = _make_mock_zabbix(name_results={"prod-vm-1": z_host})

        results = ingestor.ingest_all(
            providers={account.id: provider},
            zabbix_client=zabbix,
        )

        assert results["YC Exempt"] == "success"
        assert results["zabbix"] == "success"

        # Only prod-vm-1 should have been checked (1 MonitoringHost created)
        assert session.query(MonitoringHost).count() == 1
        mon_host = session.query(MonitoringHost).one()
        assert mon_host.name == "prod-vm-1"

        # Verify bulk fetch was used (single API call)
        zabbix.fetch_hosts.assert_called_once()

    def test_ingest_updates_exempt_on_rule_change(self, session, tenant_and_account):
        """First ingest without rules (not exempt), second with matching rule (now exempt)."""
        _, account = tenant_and_account

        # First ingest: no exclusion rules
        ingestor1 = DataIngestor(session)
        provider = _make_mock_provider(vms=[
            VMInfo(name="test-vm-1", id="ext-1", status="active"),
        ])
        ingestor1.ingest_cloud_vms(account, provider)

        vm = session.query(VM).one()
        assert vm.monitoring_exempt is False
        assert vm.monitoring_exempt_reason is None

        # Second ingest: with matching exclusion rule
        rules = [MonitoringExclusionRule(name_pattern="test-*", reason="test VMs excluded")]
        ingestor2 = DataIngestor(session, exclusion_rules=rules)
        provider2 = _make_mock_provider(vms=[
            VMInfo(name="test-vm-1", id="ext-1", status="active"),
        ])
        ingestor2.ingest_cloud_vms(account, provider2)

        session.refresh(vm)
        assert vm.monitoring_exempt is True
        assert vm.monitoring_exempt_reason == "test VMs excluded"
