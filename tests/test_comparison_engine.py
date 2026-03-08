"""Tests for ComparisonEngine."""

from infraverse.providers.base import VMInfo
from infraverse.providers.zabbix import ZabbixHost
from infraverse.comparison.engine import ComparisonEngine
from infraverse.comparison.models import VMState


def _vm(name, ips=None, provider="yandex_cloud"):
    return VMInfo(
        name=name,
        id=f"id-{name}",
        status="active",
        ip_addresses=ips or [],
        provider=provider,
    )


def _zhost(name, ips=None):
    return ZabbixHost(
        name=name,
        hostid=f"hid-{name}",
        status="active",
        ip_addresses=ips or [],
    )


class TestAllMatching:
    """All VMs present in all three systems."""

    def test_single_vm_in_all_systems(self):
        engine = ComparisonEngine()
        cloud = [_vm("web-01", ["10.0.0.1"])]
        netbox = [_vm("web-01", ["10.0.0.1"])]
        zabbix = [_zhost("web-01", ["10.0.0.1"])]

        result = engine.compare(cloud, netbox, zabbix)

        assert len(result.all_vms) == 1
        state = result.all_vms[0]
        assert state.vm_name == "web-01"
        assert state.in_cloud is True
        assert state.in_netbox is True
        assert state.in_monitoring is True
        assert state.discrepancies == []
        assert result.summary["total"] == 1
        assert result.summary["in_sync"] == 1
        assert result.summary["with_discrepancies"] == 0

    def test_multiple_vms_all_matching(self):
        engine = ComparisonEngine()
        cloud = [_vm("web-01"), _vm("db-01"), _vm("app-01")]
        netbox = [_vm("web-01"), _vm("db-01"), _vm("app-01")]
        zabbix = [_zhost("web-01"), _zhost("db-01"), _zhost("app-01")]

        result = engine.compare(cloud, netbox, zabbix)

        assert len(result.all_vms) == 3
        assert all(s.discrepancies == [] for s in result.all_vms)
        assert result.summary["in_sync"] == 3

    def test_case_insensitive_name_matching(self):
        engine = ComparisonEngine()
        cloud = [_vm("Web-01")]
        netbox = [_vm("web-01")]
        zabbix = [_zhost("WEB-01")]

        result = engine.compare(cloud, netbox, zabbix)

        assert len(result.all_vms) == 1
        assert result.all_vms[0].in_cloud is True
        assert result.all_vms[0].in_netbox is True
        assert result.all_vms[0].in_monitoring is True
        assert result.all_vms[0].discrepancies == []


class TestMissingFromOneSystem:
    """VMs missing from one of the three systems."""

    def test_in_cloud_not_in_netbox(self):
        engine = ComparisonEngine()
        cloud = [_vm("new-vm")]
        netbox = []
        zabbix = [_zhost("new-vm")]

        result = engine.compare(cloud, netbox, zabbix)

        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is False
        assert state.in_monitoring is True
        assert "in cloud but not in NetBox" in state.discrepancies

    def test_in_cloud_not_in_monitoring(self):
        engine = ComparisonEngine()
        cloud = [_vm("unmonitored")]
        netbox = [_vm("unmonitored")]
        zabbix = []

        result = engine.compare(cloud, netbox, zabbix)

        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is True
        assert state.in_monitoring is False
        assert "in cloud but not in monitoring" in state.discrepancies
        assert "in NetBox but not in monitoring" in state.discrepancies

    def test_in_netbox_not_in_cloud(self):
        engine = ComparisonEngine()
        cloud = []
        netbox = [_vm("decommissioned")]
        zabbix = [_zhost("decommissioned")]

        result = engine.compare(cloud, netbox, zabbix)

        state = result.all_vms[0]
        assert state.in_cloud is False
        assert state.in_netbox is True
        assert state.in_monitoring is True
        assert "in NetBox but not in cloud" in state.discrepancies

    def test_in_monitoring_not_in_cloud(self):
        engine = ComparisonEngine()
        cloud = []
        netbox = []
        zabbix = [_zhost("rogue-host")]

        result = engine.compare(cloud, netbox, zabbix)

        state = result.all_vms[0]
        assert state.in_cloud is False
        assert state.in_netbox is False
        assert state.in_monitoring is True
        assert "in monitoring but not in cloud" in state.discrepancies
        assert "in monitoring but not in NetBox" in state.discrepancies

    def test_in_monitoring_not_in_netbox(self):
        engine = ComparisonEngine()
        cloud = [_vm("cloud-mon")]
        netbox = []
        zabbix = [_zhost("cloud-mon")]

        result = engine.compare(cloud, netbox, zabbix)

        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is False
        assert state.in_monitoring is True
        assert "in cloud but not in NetBox" in state.discrepancies
        assert "in monitoring but not in NetBox" in state.discrepancies

    def test_in_cloud_only(self):
        engine = ComparisonEngine()
        cloud = [_vm("solo-cloud")]
        netbox = []
        zabbix = []

        result = engine.compare(cloud, netbox, zabbix)

        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is False
        assert state.in_monitoring is False
        assert "in cloud but not in NetBox" in state.discrepancies
        assert "in cloud but not in monitoring" in state.discrepancies
        assert result.summary["in_cloud_only"] == 1

    def test_in_netbox_only(self):
        engine = ComparisonEngine()
        cloud = []
        netbox = [_vm("orphan-nb")]
        zabbix = []

        result = engine.compare(cloud, netbox, zabbix)

        state = result.all_vms[0]
        assert state.in_netbox is True
        assert state.in_cloud is False
        assert state.in_monitoring is False
        assert "in NetBox but not in cloud" in state.discrepancies
        assert result.summary["in_netbox_only"] == 1

    def test_in_monitoring_only(self):
        engine = ComparisonEngine()
        cloud = []
        netbox = []
        zabbix = [_zhost("orphan-zb")]

        result = engine.compare(cloud, netbox, zabbix)

        state = result.all_vms[0]
        assert state.in_monitoring is True
        assert state.in_cloud is False
        assert state.in_netbox is False
        assert result.summary["in_monitoring_only"] == 1

    def test_mixed_present_and_missing(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a"), _vm("vm-b")]
        netbox = [_vm("vm-a"), _vm("vm-c")]
        zabbix = [_zhost("vm-a"), _zhost("vm-b")]

        result = engine.compare(cloud, netbox, zabbix)

        by_name = {s.vm_name.lower(): s for s in result.all_vms}
        assert len(by_name) == 3

        # vm-a: everywhere
        assert by_name["vm-a"].discrepancies == []

        # vm-b: cloud + zabbix, not netbox
        assert "in cloud but not in NetBox" in by_name["vm-b"].discrepancies

        # vm-c: netbox only
        assert "in NetBox but not in cloud" in by_name["vm-c"].discrepancies


class TestIPBasedMatching:
    """VMs matched by IP when names differ."""

    def test_cloud_netbox_ip_match(self):
        engine = ComparisonEngine()
        cloud = [_vm("cloud-vm", ["10.0.0.5"])]
        netbox = [_vm("nb-vm", ["10.0.0.5"])]
        zabbix = [_zhost("cloud-vm", ["10.0.0.5"])]

        result = engine.compare(cloud, netbox, zabbix)

        # cloud-vm should be matched to nb-vm via IP
        cloud_state = next(s for s in result.all_vms if s.vm_name.lower() == "cloud-vm")
        assert cloud_state.in_cloud is True
        assert cloud_state.in_netbox is True  # matched via IP
        assert cloud_state.in_monitoring is True

    def test_cloud_zabbix_ip_match(self):
        engine = ComparisonEngine()
        cloud = [_vm("cloud-vm", ["10.0.0.5"])]
        netbox = [_vm("cloud-vm", ["10.0.0.5"])]
        zabbix = [_zhost("zabbix-host", ["10.0.0.5"])]

        result = engine.compare(cloud, netbox, zabbix)

        cloud_state = next(s for s in result.all_vms if s.vm_name.lower() == "cloud-vm")
        assert cloud_state.in_cloud is True
        assert cloud_state.in_netbox is True
        assert cloud_state.in_monitoring is True  # matched via IP

    def test_netbox_zabbix_ip_match(self):
        engine = ComparisonEngine()
        cloud = []
        netbox = [_vm("nb-vm", ["10.0.0.5"])]
        zabbix = [_zhost("zb-host", ["10.0.0.5"])]

        result = engine.compare(cloud, netbox, zabbix)

        nb_state = next(s for s in result.all_vms if s.vm_name.lower() == "nb-vm")
        assert nb_state.in_netbox is True
        assert nb_state.in_monitoring is True  # matched via IP

    def test_no_ip_no_fallback_match(self):
        engine = ComparisonEngine()
        cloud = [_vm("cloud-vm", ["10.0.0.1"])]
        netbox = [_vm("nb-vm", ["10.0.0.2"])]  # different IP
        zabbix = []

        result = engine.compare(cloud, netbox, zabbix)

        # Different names, different IPs -> separate entries
        assert len(result.all_vms) == 2

    def test_multiple_ips_partial_overlap(self):
        engine = ComparisonEngine()
        cloud = [_vm("multi-ip", ["10.0.0.1", "10.0.0.2"])]
        netbox = [_vm("other-name", ["10.0.0.2", "10.0.0.3"])]
        zabbix = []

        result = engine.compare(cloud, netbox, zabbix)

        cloud_state = next(s for s in result.all_vms if s.vm_name.lower() == "multi-ip")
        assert cloud_state.in_netbox is True  # matched via shared 10.0.0.2


class TestEmptyData:
    """Empty data from one or more sources."""

    def test_all_empty(self):
        engine = ComparisonEngine()
        result = engine.compare([], [], [])

        assert result.all_vms == []
        assert result.summary["total"] == 0
        assert result.summary["in_sync"] == 0
        assert result.summary["with_discrepancies"] == 0

    def test_only_cloud_data(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-1"), _vm("vm-2")]
        result = engine.compare(cloud, [], [])

        assert len(result.all_vms) == 2
        assert all(s.in_cloud for s in result.all_vms)
        assert all(not s.in_netbox for s in result.all_vms)
        assert all(not s.in_monitoring for s in result.all_vms)
        assert result.summary["in_cloud_only"] == 2

    def test_only_netbox_data(self):
        engine = ComparisonEngine()
        netbox = [_vm("vm-1")]
        result = engine.compare([], netbox, [])

        assert len(result.all_vms) == 1
        assert result.all_vms[0].in_netbox is True
        assert result.all_vms[0].in_cloud is False

    def test_only_zabbix_data(self):
        engine = ComparisonEngine()
        zabbix = [_zhost("host-1")]
        result = engine.compare([], [], zabbix)

        assert len(result.all_vms) == 1
        assert result.all_vms[0].in_monitoring is True
        assert result.all_vms[0].in_cloud is False

    def test_cloud_and_netbox_no_zabbix_configured(self):
        """When monitoring is configured but returns no hosts, report discrepancies."""
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        netbox = [_vm("vm-1")]
        result = engine.compare(cloud, netbox, [], monitoring_configured=True)

        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is True
        assert state.in_monitoring is False
        assert "in cloud but not in monitoring" in state.discrepancies
        assert "in NetBox but not in monitoring" in state.discrepancies

    def test_cloud_and_netbox_no_zabbix_not_configured(self):
        """When monitoring is not configured, skip monitoring discrepancies."""
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        netbox = [_vm("vm-1")]
        result = engine.compare(cloud, netbox, [], monitoring_configured=False)

        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is True
        assert state.in_monitoring is False
        assert state.discrepancies == []
        assert result.summary["in_sync"] == 1

    def test_cloud_only_netbox_not_configured(self):
        """When NetBox is not configured, skip NetBox discrepancies."""
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        zabbix = [_zhost("vm-1")]
        result = engine.compare(cloud, [], zabbix, netbox_configured=False)

        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is False
        assert state.in_monitoring is True
        assert state.discrepancies == []
        assert result.summary["in_sync"] == 1

    def test_cloud_only_netbox_not_configured_monitoring_not_configured(self):
        """When both NetBox and monitoring are not configured, no discrepancies."""
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        result = engine.compare(
            cloud, [], [], netbox_configured=False, monitoring_configured=False,
        )

        state = result.all_vms[0]
        assert state.discrepancies == []
        assert result.summary["in_sync"] == 1

    def test_netbox_configured_reports_discrepancies(self):
        """When NetBox is configured, report NetBox discrepancies normally."""
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        result = engine.compare(cloud, [], [], netbox_configured=True)

        state = result.all_vms[0]
        assert "in cloud but not in NetBox" in state.discrepancies

    def test_monitoring_only_netbox_not_configured(self):
        """Monitoring-only host with NetBox not configured: only cloud discrepancy."""
        engine = ComparisonEngine()
        zabbix = [_zhost("rogue")]
        result = engine.compare([], [], zabbix, netbox_configured=False)

        state = result.all_vms[0]
        assert "in monitoring but not in cloud" in state.discrepancies
        assert "in monitoring but not in NetBox" not in state.discrepancies


class TestCloudProvider:
    """Cloud provider field is correctly set."""

    def test_cloud_provider_from_cloud_vm(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-1", provider="vcloud")]
        result = engine.compare(cloud, [], [])

        assert result.all_vms[0].cloud_provider == "vcloud"

    def test_no_cloud_provider_when_not_in_cloud(self):
        engine = ComparisonEngine()
        netbox = [_vm("vm-1")]
        result = engine.compare([], netbox, [])

        assert result.all_vms[0].cloud_provider is None

    def test_multiple_providers(self):
        engine = ComparisonEngine()
        cloud = [
            _vm("yc-vm", provider="yandex_cloud"),
            _vm("vcd-vm", provider="vcloud"),
        ]
        result = engine.compare(cloud, [], [])

        by_name = {s.vm_name.lower(): s for s in result.all_vms}
        assert by_name["yc-vm"].cloud_provider == "yandex_cloud"
        assert by_name["vcd-vm"].cloud_provider == "vcloud"


class TestDuplicateNameAcrossProviders:
    """VMs with same name from different cloud providers."""

    def test_same_name_different_providers_creates_separate_entries(self):
        engine = ComparisonEngine()
        cloud = [
            _vm("web-01", ["10.0.0.1"], provider="yandex_cloud"),
            _vm("web-01", ["10.0.0.2"], provider="vcloud"),
        ]
        result = engine.compare(cloud, [], [])

        assert len(result.all_vms) == 2
        providers = {s.cloud_provider for s in result.all_vms}
        assert providers == {"yandex_cloud", "vcloud"}

    def test_same_name_different_providers_with_netbox(self):
        engine = ComparisonEngine()
        cloud = [
            _vm("web-01", provider="yandex_cloud"),
            _vm("web-01", provider="vcloud"),
        ]
        netbox = [_vm("web-01")]
        result = engine.compare(cloud, netbox, [])

        # Both cloud entries should see the NetBox match
        assert len(result.all_vms) == 2
        assert all(s.in_netbox for s in result.all_vms)
        assert all(s.in_cloud for s in result.all_vms)


class TestIPMatchingDeduplication:
    """IP matching should merge entries and remove duplicates."""

    def test_ip_match_removes_counterpart_entry(self):
        engine = ComparisonEngine()
        cloud = [_vm("cloud-vm", ["10.0.0.5"])]
        netbox = [_vm("nb-vm", ["10.0.0.5"])]
        result = engine.compare(cloud, netbox, [])

        # Should be ONE entry (merged via IP), not two
        assert len(result.all_vms) == 1
        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is True

    def test_ip_match_three_way_merge(self):
        engine = ComparisonEngine()
        cloud = [_vm("cloud-vm", ["10.0.0.5"])]
        netbox = [_vm("nb-vm", ["10.0.0.5"])]
        zabbix = [_zhost("zb-vm", ["10.0.0.5"])]
        result = engine.compare(cloud, netbox, zabbix)

        # All three should be merged into one entry
        assert len(result.all_vms) == 1
        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is True
        assert state.in_monitoring is True
        assert state.discrepancies == []


class TestSummary:
    """Summary counts are correct."""

    def test_summary_counts(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a"), _vm("vm-b"), _vm("vm-c")]
        netbox = [_vm("vm-a"), _vm("vm-b"), _vm("vm-d")]
        zabbix = [_zhost("vm-a"), _zhost("vm-c"), _zhost("vm-e")]

        result = engine.compare(cloud, netbox, zabbix)

        assert result.summary["total"] == 5
        # vm-a: all 3 -> in sync
        assert result.summary["in_sync"] == 1
        assert result.summary["with_discrepancies"] == 4
        # vm-c: cloud + monitoring only
        assert result.summary["in_cloud_only"] == 0  # vm-c is in cloud+monitoring
        # vm-d: netbox only
        assert result.summary["in_netbox_only"] == 1
        # vm-e: monitoring only
        assert result.summary["in_monitoring_only"] == 1


class TestMissingFromNetboxAndCloud:
    """Tests for missing_from_netbox and missing_from_cloud summary keys."""

    def test_missing_from_netbox_count(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a"), _vm("vm-b"), _vm("vm-c")]
        netbox = [_vm("vm-a")]
        result = engine.compare(cloud, netbox, [])

        assert result.summary["missing_from_netbox"] == 2  # vm-b, vm-c
        assert result.summary["missing_from_cloud"] == 0

    def test_missing_from_cloud_count(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a")]
        netbox = [_vm("vm-a"), _vm("vm-b"), _vm("vm-c")]
        result = engine.compare(cloud, netbox, [])

        assert result.summary["missing_from_netbox"] == 0
        assert result.summary["missing_from_cloud"] == 2  # vm-b, vm-c

    def test_both_missing_counts(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a"), _vm("vm-b")]
        netbox = [_vm("vm-a"), _vm("vm-c")]
        result = engine.compare(cloud, netbox, [])

        assert result.summary["missing_from_netbox"] == 1  # vm-b
        assert result.summary["missing_from_cloud"] == 1  # vm-c

    def test_all_matching_zero_missing(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a"), _vm("vm-b")]
        netbox = [_vm("vm-a"), _vm("vm-b")]
        result = engine.compare(cloud, netbox, [])

        assert result.summary["missing_from_netbox"] == 0
        assert result.summary["missing_from_cloud"] == 0

    def test_empty_data_zero_missing(self):
        engine = ComparisonEngine()
        result = engine.compare([], [], [])

        assert result.summary["missing_from_netbox"] == 0
        assert result.summary["missing_from_cloud"] == 0

    def test_with_monitored_names_path(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a"), _vm("vm-b")]
        netbox = [_vm("vm-a")]
        result = engine.compare(
            cloud, netbox,
            monitored_vm_names={"vm-a"},
            monitoring_configured=True,
        )

        assert result.summary["missing_from_netbox"] == 1  # vm-b
        assert result.summary["missing_from_cloud"] == 0


class TestMonitoredVMNames:
    """ComparisonEngine with monitored_vm_names (DB-driven monitoring)."""

    def test_vm_monitored_by_name(self):
        engine = ComparisonEngine()
        cloud = [_vm("web-01", ["10.0.0.1"])]
        result = engine.compare(
            cloud, [], monitored_vm_names={"web-01"},
            netbox_configured=False,
        )
        state = result.all_vms[0]
        assert state.in_monitoring is True
        assert state.discrepancies == []

    def test_vm_not_monitored(self):
        engine = ComparisonEngine()
        cloud = [_vm("web-01")]
        result = engine.compare(
            cloud, [], monitored_vm_names=set(),
            monitoring_configured=True,
        )
        state = result.all_vms[0]
        assert state.in_monitoring is False
        assert "in cloud but not in monitoring" in state.discrepancies

    def test_case_insensitive_monitoring_match(self):
        engine = ComparisonEngine()
        cloud = [_vm("Web-Server-01")]
        result = engine.compare(
            cloud, [], monitored_vm_names={"web-server-01"},
        )
        assert result.all_vms[0].in_monitoring is True

    def test_multiple_vms_mixed_monitoring(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a"), _vm("vm-b"), _vm("vm-c")]
        result = engine.compare(
            cloud, [],
            monitored_vm_names={"vm-a", "vm-c"},
            monitoring_configured=True,
            netbox_configured=False,
        )
        by_name = {s.vm_name.lower(): s for s in result.all_vms}
        assert by_name["vm-a"].in_monitoring is True
        assert by_name["vm-b"].in_monitoring is False
        assert by_name["vm-c"].in_monitoring is True
        assert by_name["vm-a"].discrepancies == []
        assert "in cloud but not in monitoring" in by_name["vm-b"].discrepancies

    def test_monitored_names_ignores_zabbix_hosts(self):
        """When monitored_vm_names is provided, zabbix_hosts is ignored."""
        engine = ComparisonEngine()
        cloud = [_vm("web-01")]
        zabbix = [_zhost("web-01")]
        result = engine.compare(
            cloud, [],
            zabbix_hosts=zabbix,
            monitored_vm_names=set(),
            monitoring_configured=True,
        )
        # monitored_vm_names takes priority, so web-01 is NOT monitored
        assert result.all_vms[0].in_monitoring is False

    def test_monitored_names_with_netbox(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        netbox = [_vm("vm-1")]
        result = engine.compare(
            cloud, netbox,
            monitored_vm_names={"vm-1"},
        )
        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is True
        assert state.in_monitoring is True
        assert state.discrepancies == []

    def test_monitored_names_empty_means_not_configured_by_default(self):
        """Empty monitored_vm_names with monitoring_configured=False -> no discrepancies."""
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        result = engine.compare(
            cloud, [],
            monitored_vm_names=set(),
            monitoring_configured=False,
            netbox_configured=False,
        )
        state = result.all_vms[0]
        assert state.in_monitoring is False
        assert state.discrepancies == []

    def test_only_cloud_vms_appear_in_results(self):
        """With monitored_vm_names, only cloud/netbox VMs appear, not orphan monitoring names."""
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        # Monitored names include an orphan that's not in cloud
        result = engine.compare(
            cloud, [],
            monitored_vm_names={"vm-1", "orphan-host"},
            monitoring_configured=True,
        )
        # Only vm-1 should appear, not orphan-host
        assert len(result.all_vms) == 1
        assert result.all_vms[0].vm_name == "vm-1"
        assert result.all_vms[0].in_monitoring is True

    def test_summary_with_monitored_names(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-a"), _vm("vm-b")]
        result = engine.compare(
            cloud, [],
            monitored_vm_names={"vm-a"},
            monitoring_configured=True,
            netbox_configured=False,
        )
        assert result.summary["total"] == 2
        assert result.summary["in_sync"] == 1  # vm-a: cloud + monitoring
        assert result.summary["with_discrepancies"] == 1  # vm-b: cloud only


class TestMonitoringExemption:
    """Tests for monitoring exemption flag on VMState."""

    def test_exempt_vm_no_monitoring_discrepancy(self):
        """VM in cloud, not in monitoring, but exempt -> no monitoring discrepancy."""
        engine = ComparisonEngine()
        state = VMState(
            vm_name="exempt-vm",
            in_cloud=True,
            in_netbox=True,
            in_monitoring=False,
            is_monitoring_exempt=True,
            monitoring_exempt_reason="Service VM",
        )
        discs = engine._compute_discrepancies(state, monitoring_configured=True)
        assert "in cloud but not in monitoring" not in discs
        assert "in NetBox but not in monitoring" not in discs
        assert discs == []

    def test_exempt_vm_still_gets_netbox_discrepancy(self):
        """Exempt VM missing from NetBox still gets NetBox discrepancy."""
        engine = ComparisonEngine()
        state = VMState(
            vm_name="exempt-no-nb",
            in_cloud=True,
            in_netbox=False,
            in_monitoring=False,
            is_monitoring_exempt=True,
        )
        discs = engine._compute_discrepancies(
            state, monitoring_configured=True, netbox_configured=True,
        )
        assert "in cloud but not in NetBox" in discs
        assert "in cloud but not in monitoring" not in discs

    def test_exempt_vm_in_sync_when_in_cloud_and_netbox(self):
        """Exempt VM in cloud + netbox -> in_sync (no monitoring discrepancy)."""
        engine = ComparisonEngine()
        state = VMState(
            vm_name="exempt-synced",
            in_cloud=True,
            in_netbox=True,
            in_monitoring=False,
            is_monitoring_exempt=True,
        )
        discs = engine._compute_discrepancies(
            state, monitoring_configured=True, netbox_configured=True,
        )
        assert discs == []

    def test_summary_monitoring_exempt_count(self):
        """summary['monitoring_exempt'] counts correctly."""
        engine = ComparisonEngine()
        states = [
            VMState(vm_name="vm-a", in_cloud=True, in_netbox=True, in_monitoring=True),
            VMState(
                vm_name="vm-b", in_cloud=True, in_netbox=True, in_monitoring=False,
                is_monitoring_exempt=True, monitoring_exempt_reason="Infra VM",
            ),
            VMState(
                vm_name="vm-c", in_cloud=True, in_netbox=True, in_monitoring=False,
                is_monitoring_exempt=True, monitoring_exempt_reason="Test VM",
            ),
            VMState(vm_name="vm-d", in_cloud=True, in_netbox=True, in_monitoring=False),
        ]
        # Compute discrepancies so summary counts work properly
        for s in states:
            s.discrepancies = engine._compute_discrepancies(s)
        summary = engine.build_summary(states)
        assert summary["monitoring_exempt"] == 2

    def test_summary_missing_from_monitoring_excludes_exempt(self):
        """summary['missing_from_monitoring'] does NOT count exempt VMs."""
        engine = ComparisonEngine()
        states = [
            VMState(vm_name="vm-a", in_cloud=True, in_netbox=True, in_monitoring=True),
            VMState(
                vm_name="vm-b", in_cloud=True, in_netbox=True, in_monitoring=False,
                is_monitoring_exempt=True,
            ),
            VMState(vm_name="vm-c", in_cloud=True, in_netbox=True, in_monitoring=False),
            VMState(
                vm_name="vm-d", in_cloud=True, in_netbox=True, in_monitoring=False,
                is_monitoring_exempt=True,
            ),
        ]
        for s in states:
            s.discrepancies = engine._compute_discrepancies(s)
        summary = engine.build_summary(states)
        # Only vm-c is missing from monitoring (not exempt)
        assert summary["missing_from_monitoring"] == 1
        # vm-b and vm-d are exempt
        assert summary["monitoring_exempt"] == 2

    def test_non_exempt_vm_still_gets_monitoring_discrepancy(self):
        """Non-exempt VM without monitoring is still flagged."""
        engine = ComparisonEngine()
        state = VMState(
            vm_name="normal-vm",
            in_cloud=True,
            in_netbox=True,
            in_monitoring=False,
            is_monitoring_exempt=False,
        )
        discs = engine._compute_discrepancies(
            state, monitoring_configured=True, netbox_configured=True,
        )
        assert "in cloud but not in monitoring" in discs
        assert "in NetBox but not in monitoring" in discs
