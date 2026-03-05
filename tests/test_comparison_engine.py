"""Tests for ComparisonEngine."""

from netbox_sync.clients.base import VMInfo
from netbox_sync.clients.zabbix import ZabbixHost
from netbox_sync.comparison.engine import ComparisonEngine


def _vm(name, ips=None, provider="yandex-cloud"):
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

    def test_cloud_and_netbox_no_zabbix(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-1")]
        netbox = [_vm("vm-1")]
        result = engine.compare(cloud, netbox, [])

        state = result.all_vms[0]
        assert state.in_cloud is True
        assert state.in_netbox is True
        assert state.in_monitoring is False
        assert "in cloud but not in monitoring" in state.discrepancies
        assert "in NetBox but not in monitoring" in state.discrepancies


class TestCloudProvider:
    """Cloud provider field is correctly set."""

    def test_cloud_provider_from_cloud_vm(self):
        engine = ComparisonEngine()
        cloud = [_vm("vm-1", provider="vcloud-director")]
        result = engine.compare(cloud, [], [])

        assert result.all_vms[0].cloud_provider == "vcloud-director"

    def test_no_cloud_provider_when_not_in_cloud(self):
        engine = ComparisonEngine()
        netbox = [_vm("vm-1")]
        result = engine.compare([], netbox, [])

        assert result.all_vms[0].cloud_provider is None

    def test_multiple_providers(self):
        engine = ComparisonEngine()
        cloud = [
            _vm("yc-vm", provider="yandex-cloud"),
            _vm("vcd-vm", provider="vcloud-director"),
        ]
        result = engine.compare(cloud, [], [])

        by_name = {s.vm_name.lower(): s for s in result.all_vms}
        assert by_name["yc-vm"].cloud_provider == "yandex-cloud"
        assert by_name["vcd-vm"].cloud_provider == "vcloud-director"


class TestDuplicateNameAcrossProviders:
    """VMs with same name from different cloud providers."""

    def test_same_name_different_providers_creates_separate_entries(self):
        engine = ComparisonEngine()
        cloud = [
            _vm("web-01", ["10.0.0.1"], provider="yandex-cloud"),
            _vm("web-01", ["10.0.0.2"], provider="vcloud-director"),
        ]
        result = engine.compare(cloud, [], [])

        assert len(result.all_vms) == 2
        providers = {s.cloud_provider for s in result.all_vms}
        assert providers == {"yandex-cloud", "vcloud-director"}

    def test_same_name_different_providers_with_netbox(self):
        engine = ComparisonEngine()
        cloud = [
            _vm("web-01", provider="yandex-cloud"),
            _vm("web-01", provider="vcloud-director"),
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
