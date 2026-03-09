"""Tests for NetBox VM CRUD methods (netbox_vms.py mixin)."""

import pytest
from unittest.mock import MagicMock, patch

from infraverse.providers.base import VMInfo
from infraverse.providers.netbox import NetBoxClient


class MockRecord:
    """Mock pynetbox Record object."""

    def __init__(self, id, name=None, slug=None, **kwargs):
        self.id = id
        self.name = name
        self.slug = slug
        self.save = MagicMock(return_value=True)
        self.delete = MagicMock(return_value=True)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __str__(self):
        return self.name or str(self.id)


@pytest.fixture
def nb_client():
    """Create a NetBoxClient with mocked pynetbox API."""
    with patch('infraverse.providers.netbox.pynetbox') as mock_pynetbox:
        mock_api = MagicMock()
        mock_pynetbox.api.return_value = mock_api

        client = NetBoxClient("https://netbox.example.com", "test-token", dry_run=False)
        client._mock_api = mock_api
        return client


@pytest.fixture
def nb_client_dry_run():
    """Create a NetBoxClient in dry-run mode."""
    with patch('infraverse.providers.netbox.pynetbox') as mock_pynetbox:
        mock_api = MagicMock()
        mock_pynetbox.api.return_value = mock_api

        client = NetBoxClient("https://netbox.example.com", "test-token", dry_run=True)
        client._mock_api = mock_api
        return client


class TestCreateVM:
    def test_create_vm_success(self, nb_client):
        nb_client._sync_tag_id = 1
        vm = MockRecord(100, name="web-1")
        nb_client.nb.virtualization.virtual_machines.create.return_value = vm

        result = nb_client.create_vm({
            "name": "web-1",
            "cluster": 1,
            "vcpus": 2,
            "memory": 4096,
            "status": "active",
        })

        assert result.id == 100
        assert result.name == "web-1"

    def test_create_vm_removes_disk_field(self, nb_client):
        nb_client._sync_tag_id = 1
        vm = MockRecord(101, name="web-2")
        nb_client.nb.virtualization.virtual_machines.create.return_value = vm

        nb_client.create_vm({
            "name": "web-2",
            "cluster": 1,
            "disk": 50,  # Should be removed
        })

        call_args = nb_client.nb.virtualization.virtual_machines.create.call_args[0][0]
        assert "disk" not in call_args

    def test_create_vm_adds_tag(self, nb_client):
        nb_client._sync_tag_id = 5
        vm = MockRecord(102, name="web-3")
        nb_client.nb.virtualization.virtual_machines.create.return_value = vm

        nb_client.create_vm({"name": "web-3", "cluster": 1})

        call_args = nb_client.nb.virtualization.virtual_machines.create.call_args[0][0]
        assert call_args["tags"] == [5]

    def test_create_vm_dry_run(self, nb_client_dry_run):
        result = nb_client_dry_run.create_vm({"name": "test-vm", "cluster": 1})

        assert result is not None
        assert result.id == 1
        assert result.name == "test-vm"
        nb_client_dry_run.nb.virtualization.virtual_machines.create.assert_not_called()

    def test_create_vm_failure_returns_none(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.virtualization.virtual_machines.create.side_effect = Exception("API error")

        result = nb_client.create_vm({"name": "fail-vm", "cluster": 1})

        assert result is None

    def test_create_vm_with_custom_tag_slug(self, nb_client):
        nb_client._sync_tag_cache = {"custom-tag": 42}
        vm = MockRecord(103, name="web-4")
        nb_client.nb.virtualization.virtual_machines.create.return_value = vm

        result = nb_client.create_vm({"name": "web-4", "cluster": 1}, tag_slug="custom-tag")

        assert result.id == 103
        call_args = nb_client.nb.virtualization.virtual_machines.create.call_args[0][0]
        assert call_args["tags"] == [42]


class TestUpdateVM:
    def test_update_vm_success(self, nb_client):
        nb_client._sync_tag_id = 1
        vm = MockRecord(100, name="web-1", tags=[])
        nb_client.nb.virtualization.virtual_machines.get.return_value = vm

        result = nb_client.update_vm(100, {"vcpus": 4, "memory": 8192})

        assert result is True
        assert vm.vcpus == 4
        assert vm.memory == 8192

    def test_update_vm_removes_disk_field(self, nb_client):
        nb_client._sync_tag_id = 1
        vm = MockRecord(100, name="web-1", tags=[])
        nb_client.nb.virtualization.virtual_machines.get.return_value = vm

        result = nb_client.update_vm(100, {"vcpus": 4, "disk": 100})

        assert result is True
        assert vm.vcpus == 4
        assert not hasattr(vm, 'disk') or getattr(vm, 'disk', None) is None

    def test_update_vm_not_found(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.get.return_value = None

        result = nb_client.update_vm(999, {"vcpus": 4})

        assert result is False

    def test_update_vm_dry_run(self, nb_client_dry_run):
        result = nb_client_dry_run.update_vm(100, {"vcpus": 4})

        assert result is True
        nb_client_dry_run.nb.virtualization.virtual_machines.get.assert_not_called()

    def test_update_vm_api_error(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.get.side_effect = Exception("API error")

        result = nb_client.update_vm(100, {"vcpus": 4})

        assert result is False


class TestGetVmByName:
    def test_found(self, nb_client):
        vm = MockRecord(100, name="web-1")
        nb_client.nb.virtualization.virtual_machines.get.return_value = vm

        result = nb_client.get_vm_by_name("web-1")

        assert result.id == 100

    def test_not_found(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.get.return_value = None

        result = nb_client.get_vm_by_name("nonexistent")

        assert result is None

    def test_error_returns_none(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.get.side_effect = Exception("error")

        result = nb_client.get_vm_by_name("error-vm")

        assert result is None


class TestGetVmByCustomField:
    def test_found(self, nb_client):
        vm = MockRecord(100, name="web-1")
        nb_client.nb.virtualization.virtual_machines.filter.return_value = [vm]

        result = nb_client.get_vm_by_custom_field("yc_id", "abc123")

        assert result.id == 100
        nb_client.nb.virtualization.virtual_machines.filter.assert_called_with(cf_yc_id="abc123")

    def test_not_found(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.filter.return_value = []

        result = nb_client.get_vm_by_custom_field("yc_id", "nonexistent")

        assert result is None

    def test_error_returns_none(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.filter.side_effect = Exception("error")

        result = nb_client.get_vm_by_custom_field("yc_id", "abc")

        assert result is None


class TestFetchVms:
    def test_fetch_vms_success(self, nb_client):
        vms = [MockRecord(1, name="vm1"), MockRecord(2, name="vm2")]
        nb_client.nb.virtualization.virtual_machines.all.return_value = vms

        result = nb_client.fetch_vms()

        assert len(result) == 2

    def test_fetch_vms_error_returns_empty(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.all.side_effect = Exception("error")

        result = nb_client.fetch_vms()

        assert result == []


class TestFetchAllVms:
    def _make_vm_record(self, id, name, status_value="active", vcpus=2, memory=4096,
                        primary_ip4=None, primary_ip6=None, cluster=None):
        """Helper to create a mock VM record with pynetbox-like attributes."""
        status = MagicMock()
        status.value = status_value
        vm = MockRecord(id, name=name, status=status, vcpus=vcpus, memory=memory,
                        primary_ip4=primary_ip4, primary_ip6=primary_ip6, cluster=cluster)
        return vm

    def test_converts_vms_to_vminfo(self, nb_client):
        ip4 = MagicMock()
        ip4.__str__ = lambda self: "10.0.0.1/24"
        cluster = MagicMock()
        cluster.__str__ = lambda self: "my-cloud/prod"
        vm = self._make_vm_record(100, "web-1", primary_ip4=ip4, cluster=cluster)
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert len(result) == 1
        assert isinstance(result[0], VMInfo)
        assert result[0].name == "web-1"
        assert result[0].id == "100"
        assert result[0].status == "active"
        assert result[0].ip_addresses == ["10.0.0.1"]
        assert result[0].vcpus == 2
        assert result[0].memory_mb == 4096
        assert result[0].provider == "netbox"
        assert result[0].folder_name == "my-cloud/prod"

    def test_handles_both_ipv4_and_ipv6(self, nb_client):
        ip4 = MagicMock()
        ip4.__str__ = lambda self: "10.0.0.5/32"
        ip6 = MagicMock()
        ip6.__str__ = lambda self: "2001:db8::1/128"
        vm = self._make_vm_record(101, "dual-stack", primary_ip4=ip4, primary_ip6=ip6)
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert result[0].ip_addresses == ["10.0.0.5", "2001:db8::1"]

    def test_handles_no_ips(self, nb_client):
        vm = self._make_vm_record(102, "no-ip")
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert result[0].ip_addresses == []

    def test_maps_offline_status(self, nb_client):
        vm = self._make_vm_record(103, "stopped-vm", status_value="offline")
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert result[0].status == "offline"

    def test_maps_decommissioning_status(self, nb_client):
        vm = self._make_vm_record(104, "decom-vm", status_value="decommissioning")
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert result[0].status == "offline"

    def test_maps_unknown_status(self, nb_client):
        vm = self._make_vm_record(105, "weird-vm", status_value="planned")
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert result[0].status == "unknown"

    def test_handles_none_vcpus_and_memory(self, nb_client):
        vm = self._make_vm_record(106, "bare-vm", vcpus=None, memory=None)
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert result[0].vcpus == 0
        assert result[0].memory_mb == 0

    def test_multiple_vms(self, nb_client):
        vms = [
            self._make_vm_record(1, "vm-a"),
            self._make_vm_record(2, "vm-b"),
            self._make_vm_record(3, "vm-c"),
        ]
        nb_client.nb.virtualization.virtual_machines.all.return_value = vms

        result = nb_client.fetch_all_vms()

        assert len(result) == 3
        assert [v.name for v in result] == ["vm-a", "vm-b", "vm-c"]

    def test_error_propagates_exception(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.all.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            nb_client.fetch_all_vms()

    def test_empty_netbox_returns_empty_list(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.all.return_value = []

        result = nb_client.fetch_all_vms()

        assert result == []

    def test_no_cluster_gives_empty_folder(self, nb_client):
        vm = self._make_vm_record(107, "orphan-vm", cluster=None)
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert result[0].folder_name == ""

    def test_tenant_name_extracted(self, nb_client):
        tenant = MagicMock()
        tenant.__str__ = lambda self: "acme-corp"
        vm = self._make_vm_record(108, "tenant-vm")
        vm.tenant = tenant
        nb_client.nb.virtualization.virtual_machines.all.return_value = [vm]

        result = nb_client.fetch_all_vms()

        assert result[0].tenant_name == "acme-corp"
