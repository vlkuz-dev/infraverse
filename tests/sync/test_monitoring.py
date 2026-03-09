"""Tests for per-VM monitoring check logic."""

import pytest
from dataclasses import dataclass
from unittest.mock import MagicMock

from infraverse.providers.zabbix import ZabbixHost
from infraverse.sync.monitoring import (
    _build_host_lookups,
    _check_vm_from_lookups,
    check_vm_monitoring,
    check_all_vms_monitoring,
)


@dataclass
class FakeVM:
    """Minimal VM-like object for testing."""
    name: str
    ip_addresses: list[str] | None = None


def _make_zabbix_client(
    by_name_return=None,
    by_ip_returns=None,
    by_name_error=None,
    by_ip_error=None,
):
    """Create a mock ZabbixClient with configurable search behavior."""
    client = MagicMock()
    if by_name_error:
        client.search_host_by_name.side_effect = by_name_error
    else:
        client.search_host_by_name.return_value = by_name_return

    if by_ip_error:
        client.search_host_by_ip.side_effect = by_ip_error
    elif by_ip_returns is not None:
        client.search_host_by_ip.side_effect = by_ip_returns
    else:
        client.search_host_by_ip.return_value = None
    return client


class TestCheckVmMonitoring:
    def test_found_by_name(self):
        zabbix_host = ZabbixHost(
            name="web-server-1", hostid="101", status="active", ip_addresses=["10.0.0.1"]
        )
        vm = FakeVM(name="web-server-1", ip_addresses=["10.0.0.1"])
        client = _make_zabbix_client(by_name_return=zabbix_host)

        result = check_vm_monitoring(vm, client)

        assert result.found is True
        assert result.host == zabbix_host
        assert result.matched_by == "name"
        client.search_host_by_name.assert_called_once_with("web-server-1")
        client.search_host_by_ip.assert_not_called()

    def test_found_by_ip_fallback(self):
        zabbix_host = ZabbixHost(
            name="web-1-zabbix", hostid="102", status="active", ip_addresses=["10.0.0.5"]
        )
        vm = FakeVM(name="web-server-1", ip_addresses=["10.0.0.5"])
        client = _make_zabbix_client(by_name_return=None, by_ip_returns=[zabbix_host])

        result = check_vm_monitoring(vm, client)

        assert result.found is True
        assert result.host == zabbix_host
        assert result.matched_by == "ip"
        client.search_host_by_name.assert_called_once_with("web-server-1")
        client.search_host_by_ip.assert_called_once_with("10.0.0.5")

    def test_found_by_second_ip(self):
        zabbix_host = ZabbixHost(
            name="db-zabbix", hostid="103", status="active", ip_addresses=["10.0.0.20"]
        )
        vm = FakeVM(name="db-server", ip_addresses=["10.0.0.10", "10.0.0.20"])
        client = _make_zabbix_client(by_name_return=None, by_ip_returns=[None, zabbix_host])

        result = check_vm_monitoring(vm, client)

        assert result.found is True
        assert result.host == zabbix_host
        assert result.matched_by == "ip"
        assert client.search_host_by_ip.call_count == 2
        client.search_host_by_ip.assert_any_call("10.0.0.10")
        client.search_host_by_ip.assert_any_call("10.0.0.20")

    def test_not_found(self):
        vm = FakeVM(name="unknown-vm", ip_addresses=["10.0.0.99"])
        client = _make_zabbix_client(by_name_return=None, by_ip_returns=[None])

        result = check_vm_monitoring(vm, client)

        assert result.found is False
        assert result.host is None
        assert result.matched_by is None
        client.search_host_by_name.assert_called_once_with("unknown-vm")
        client.search_host_by_ip.assert_called_once_with("10.0.0.99")

    def test_not_found_no_ips(self):
        vm = FakeVM(name="no-ip-vm", ip_addresses=None)
        client = _make_zabbix_client(by_name_return=None)

        result = check_vm_monitoring(vm, client)

        assert result.found is False
        assert result.host is None
        client.search_host_by_name.assert_called_once_with("no-ip-vm")
        client.search_host_by_ip.assert_not_called()

    def test_not_found_empty_ips(self):
        vm = FakeVM(name="empty-ip-vm", ip_addresses=[])
        client = _make_zabbix_client(by_name_return=None)

        result = check_vm_monitoring(vm, client)

        assert result.found is False
        client.search_host_by_ip.assert_not_called()

    def test_api_error_on_name_search_propagates(self):
        vm = FakeVM(name="error-vm", ip_addresses=["10.0.0.1"])
        client = _make_zabbix_client(by_name_error=RuntimeError("API error"))

        with pytest.raises(RuntimeError, match="API error"):
            check_vm_monitoring(vm, client)

    def test_api_error_on_ip_search_propagates(self):
        vm = FakeVM(name="error-vm", ip_addresses=["10.0.0.1"])
        client = _make_zabbix_client(
            by_name_return=None,
            by_ip_error=RuntimeError("IP lookup failed"),
        )

        with pytest.raises(RuntimeError, match="IP lookup failed"):
            check_vm_monitoring(vm, client)


def _make_bulk_client(hosts=None, fetch_error=None):
    """Create a mock ZabbixClient with bulk fetch behavior."""
    client = MagicMock()
    if fetch_error:
        client.fetch_hosts.side_effect = fetch_error
    else:
        client.fetch_hosts.return_value = hosts or []
    return client


class TestBuildHostLookups:
    def test_builds_name_and_ip_dicts(self):
        h1 = ZabbixHost(name="web", hostid="1", status="active", ip_addresses=["10.0.0.1"])
        h2 = ZabbixHost(name="db", hostid="2", status="active", ip_addresses=["10.0.0.2"])
        by_name, by_ip = _build_host_lookups([h1, h2])

        assert by_name["web"] is h1
        assert by_name["db"] is h2
        assert by_ip["10.0.0.1"] is h1
        assert by_ip["10.0.0.2"] is h2

    def test_first_host_wins_duplicate_name(self):
        h1 = ZabbixHost(name="dup", hostid="1", status="active")
        h2 = ZabbixHost(name="dup", hostid="2", status="active")
        by_name, _ = _build_host_lookups([h1, h2])

        assert by_name["dup"] is h1

    def test_first_host_wins_duplicate_ip(self):
        h1 = ZabbixHost(name="a", hostid="1", status="active", ip_addresses=["10.0.0.1"])
        h2 = ZabbixHost(name="b", hostid="2", status="active", ip_addresses=["10.0.0.1"])
        _, by_ip = _build_host_lookups([h1, h2])

        assert by_ip["10.0.0.1"] is h1

    def test_multiple_ips_per_host(self):
        h = ZabbixHost(name="multi", hostid="1", status="active", ip_addresses=["10.0.0.1", "10.0.0.2"])
        _, by_ip = _build_host_lookups([h])

        assert by_ip["10.0.0.1"] is h
        assert by_ip["10.0.0.2"] is h

    def test_empty_list(self):
        by_name, by_ip = _build_host_lookups([])
        assert by_name == {}
        assert by_ip == {}


class TestCheckVmFromLookups:
    def test_match_by_name(self):
        host = ZabbixHost(name="web", hostid="1", status="active", ip_addresses=["10.0.0.1"])
        by_name = {"web": host}
        by_ip = {"10.0.0.1": host}
        vm = FakeVM(name="web", ip_addresses=["10.0.0.1"])

        result = _check_vm_from_lookups(vm, by_name, by_ip)

        assert result.found is True
        assert result.matched_by == "name"
        assert result.host is host

    def test_match_by_ip_when_name_differs(self):
        host = ZabbixHost(name="web-zabbix", hostid="1", status="active", ip_addresses=["10.0.0.1"])
        by_name = {"web-zabbix": host}
        by_ip = {"10.0.0.1": host}
        vm = FakeVM(name="web", ip_addresses=["10.0.0.1"])

        result = _check_vm_from_lookups(vm, by_name, by_ip)

        assert result.found is True
        assert result.matched_by == "ip"
        assert result.host is host

    def test_match_by_second_ip(self):
        host = ZabbixHost(name="db-zabbix", hostid="1", status="active", ip_addresses=["10.0.0.2"])
        by_name = {"db-zabbix": host}
        by_ip = {"10.0.0.2": host}
        vm = FakeVM(name="db", ip_addresses=["10.0.0.1", "10.0.0.2"])

        result = _check_vm_from_lookups(vm, by_name, by_ip)

        assert result.found is True
        assert result.matched_by == "ip"

    def test_not_found(self):
        vm = FakeVM(name="unknown", ip_addresses=["10.0.0.99"])
        result = _check_vm_from_lookups(vm, {}, {})

        assert result.found is False
        assert result.host is None

    def test_not_found_no_ips(self):
        vm = FakeVM(name="no-ip", ip_addresses=None)
        result = _check_vm_from_lookups(vm, {}, {})

        assert result.found is False

    def test_name_takes_priority_over_ip(self):
        """Even if IP matches a different host, name match wins."""
        host_a = ZabbixHost(name="web", hostid="1", status="active", ip_addresses=["10.0.0.1"])
        host_b = ZabbixHost(name="other", hostid="2", status="active", ip_addresses=["10.0.0.1"])
        by_name = {"web": host_a, "other": host_b}
        by_ip = {"10.0.0.1": host_b}
        vm = FakeVM(name="web", ip_addresses=["10.0.0.1"])

        result = _check_vm_from_lookups(vm, by_name, by_ip)

        assert result.matched_by == "name"
        assert result.host is host_a


class TestCheckAllVmsBulkFetch:
    """Tests for the bulk fetch (default) path in check_all_vms_monitoring."""

    def test_all_found_by_name(self):
        host1 = ZabbixHost(name="vm-1", hostid="101", status="active")
        host2 = ZabbixHost(name="vm-2", hostid="102", status="active")
        vms = [FakeVM(name="vm-1"), FakeVM(name="vm-2")]
        client = _make_bulk_client(hosts=[host1, host2])

        results = check_all_vms_monitoring(vms, client)

        assert len(results) == 2
        assert results[0].found is True
        assert results[0].vm_name == "vm-1"
        assert results[0].host == host1
        assert results[1].found is True
        assert results[1].vm_name == "vm-2"
        # Bulk fetch: single API call, no per-VM calls
        client.fetch_hosts.assert_called_once()
        client.search_host_by_name.assert_not_called()
        client.search_host_by_ip.assert_not_called()

    def test_none_found(self):
        vms = [FakeVM(name="vm-1"), FakeVM(name="vm-2")]
        client = _make_bulk_client(hosts=[])

        results = check_all_vms_monitoring(vms, client)

        assert len(results) == 2
        assert all(r.found is False for r in results)
        assert results[0].vm_name == "vm-1"
        assert results[1].vm_name == "vm-2"
        client.fetch_hosts.assert_called_once()

    def test_mixed_name_and_ip_matches(self):
        host_by_name = ZabbixHost(name="vm-1", hostid="101", status="active")
        host_by_ip = ZabbixHost(
            name="vm-2-zabbix", hostid="102", status="active", ip_addresses=["10.0.0.2"]
        )
        vms = [
            FakeVM(name="vm-1"),
            FakeVM(name="vm-2", ip_addresses=["10.0.0.2"]),
        ]
        client = _make_bulk_client(hosts=[host_by_name, host_by_ip])

        results = check_all_vms_monitoring(vms, client)

        assert results[0].found is True
        assert results[0].matched_by == "name"
        assert results[1].found is True
        assert results[1].matched_by == "ip"
        client.fetch_hosts.assert_called_once()

    def test_mixed_found_and_not_found(self):
        host1 = ZabbixHost(name="vm-1", hostid="101", status="active")
        vms = [
            FakeVM(name="vm-1"),
            FakeVM(name="vm-2", ip_addresses=["10.0.0.5"]),
            FakeVM(name="vm-3"),
        ]
        client = _make_bulk_client(hosts=[host1])

        results = check_all_vms_monitoring(vms, client)

        assert len(results) == 3
        assert results[0].found is True
        assert results[0].matched_by == "name"
        assert results[1].found is False
        assert results[2].found is False

    def test_empty_vm_list(self):
        client = _make_bulk_client()

        results = check_all_vms_monitoring([], client)

        assert results == []
        # No fetch needed for empty VM list
        client.fetch_hosts.assert_not_called()

    def test_result_contains_vm_name(self):
        vms = [FakeVM(name="my-special-vm")]
        client = _make_bulk_client(hosts=[])

        results = check_all_vms_monitoring(vms, client)

        assert results[0].vm_name == "my-special-vm"


class TestCheckAllVmsFallback:
    """Tests for the per-VM fallback path when bulk fetch fails."""

    def test_fallback_on_fetch_error(self):
        """When fetch_hosts raises, falls back to per-VM queries."""
        host1 = ZabbixHost(name="vm-1", hostid="101", status="active")
        vms = [FakeVM(name="vm-1"), FakeVM(name="vm-2")]
        client = MagicMock()
        client.fetch_hosts.side_effect = RuntimeError("Bulk fetch failed")
        client.search_host_by_name.side_effect = [host1, None]
        client.search_host_by_ip.return_value = None

        results = check_all_vms_monitoring(vms, client)

        assert len(results) == 2
        assert results[0].found is True
        assert results[0].matched_by == "name"
        assert results[1].found is False
        # Per-VM calls were made
        assert client.search_host_by_name.call_count == 2

    def test_fallback_ip_match(self):
        """Fallback path still does name-first-then-IP lookup."""
        host_by_ip = ZabbixHost(
            name="vm-zabbix", hostid="101", status="active", ip_addresses=["10.0.0.1"]
        )
        vms = [FakeVM(name="vm-1", ip_addresses=["10.0.0.1"])]
        client = MagicMock()
        client.fetch_hosts.side_effect = RuntimeError("Bulk fetch failed")
        client.search_host_by_name.return_value = None
        client.search_host_by_ip.return_value = host_by_ip

        results = check_all_vms_monitoring(vms, client)

        assert results[0].found is True
        assert results[0].matched_by == "ip"

    def test_fallback_api_error_isolated_per_vm(self):
        """In fallback mode, a per-VM error doesn't abort the batch."""
        host2 = ZabbixHost(name="vm-2", hostid="102", status="active")
        vms = [FakeVM(name="vm-1"), FakeVM(name="vm-2"), FakeVM(name="vm-3")]
        client = MagicMock()
        client.fetch_hosts.side_effect = RuntimeError("Bulk fetch failed")
        client.search_host_by_name.side_effect = [
            RuntimeError("API error"),
            host2,
            None,
        ]
        client.search_host_by_ip.return_value = None

        results = check_all_vms_monitoring(vms, client)

        assert len(results) == 3
        assert results[0].found is False
        assert results[0].vm_name == "vm-1"
        assert results[1].found is True
        assert results[1].vm_name == "vm-2"
        assert results[2].found is False
        assert results[2].vm_name == "vm-3"

    def test_fallback_mixed_name_and_ip(self):
        host_by_name = ZabbixHost(name="vm-1", hostid="101", status="active")
        host_by_ip = ZabbixHost(
            name="vm-2-zabbix", hostid="102", status="active", ip_addresses=["10.0.0.2"]
        )
        vms = [
            FakeVM(name="vm-1"),
            FakeVM(name="vm-2", ip_addresses=["10.0.0.2"]),
        ]
        client = MagicMock()
        client.fetch_hosts.side_effect = RuntimeError("Bulk fetch failed")
        client.search_host_by_name.side_effect = [host_by_name, None]
        client.search_host_by_ip.return_value = host_by_ip

        results = check_all_vms_monitoring(vms, client)

        assert results[0].found is True
        assert results[0].matched_by == "name"
        assert results[1].found is True
        assert results[1].matched_by == "ip"
