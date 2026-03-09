"""Tests for NetBox client."""

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

        # Make the mock api accessible for test setup
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


class TestSetVmPrimaryIp:
    def test_set_primary_ip_success(self, nb_client):
        vm = MockRecord(100, name="web-1")
        ip = MockRecord(200, address="10.0.0.5/24", assigned_object_id=50)
        iface = MockRecord(50, name="eth0")

        nb_client.nb.virtualization.virtual_machines.get.return_value = vm
        nb_client.nb.ipam.ip_addresses.get.return_value = ip
        nb_client.nb.virtualization.interfaces.filter.return_value = [iface]

        result = nb_client.set_vm_primary_ip(100, 200, ip_version=4)

        assert result is True
        assert vm.primary_ip4 == 200

    def test_set_primary_ip_assigns_to_interface_if_needed(self, nb_client):
        vm = MockRecord(100, name="web-1")
        ip = MockRecord(200, address="10.0.0.5/24", assigned_object_id=999)  # Not on this VM
        iface = MockRecord(50, name="eth0")

        nb_client.nb.virtualization.virtual_machines.get.return_value = vm
        nb_client.nb.ipam.ip_addresses.get.return_value = ip
        nb_client.nb.virtualization.interfaces.filter.return_value = [iface]

        result = nb_client.set_vm_primary_ip(100, 200)

        assert result is True
        # Should have assigned IP to VM's first interface
        assert ip.assigned_object_id == 50

    def test_set_primary_ip_vm_not_found(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.get.return_value = None

        result = nb_client.set_vm_primary_ip(999, 200)

        assert result is False

    def test_set_primary_ip_ip_not_found(self, nb_client):
        vm = MockRecord(100, name="web-1")
        nb_client.nb.virtualization.virtual_machines.get.return_value = vm
        nb_client.nb.ipam.ip_addresses.get.return_value = None

        result = nb_client.set_vm_primary_ip(100, 999)

        assert result is False

    def test_set_primary_ip_invalid_version(self, nb_client):
        vm = MockRecord(100, name="web-1")
        ip = MockRecord(200, address="10.0.0.5/24", assigned_object_id=50)
        iface = MockRecord(50, name="eth0")

        nb_client.nb.virtualization.virtual_machines.get.return_value = vm
        nb_client.nb.ipam.ip_addresses.get.return_value = ip
        nb_client.nb.virtualization.interfaces.filter.return_value = [iface]

        result = nb_client.set_vm_primary_ip(100, 200, ip_version=5)

        assert result is False

    def test_set_primary_ipv6(self, nb_client):
        vm = MockRecord(100, name="web-1")
        ip = MockRecord(200, address="::1/128", assigned_object_id=50)
        iface = MockRecord(50, name="eth0")

        nb_client.nb.virtualization.virtual_machines.get.return_value = vm
        nb_client.nb.ipam.ip_addresses.get.return_value = ip
        nb_client.nb.virtualization.interfaces.filter.return_value = [iface]

        result = nb_client.set_vm_primary_ip(100, 200, ip_version=6)

        assert result is True
        assert vm.primary_ip6 == 200

    def test_dry_run(self, nb_client_dry_run):
        result = nb_client_dry_run.set_vm_primary_ip(100, 200)

        assert result is True
        nb_client_dry_run.nb.virtualization.virtual_machines.get.assert_not_called()

    def test_no_interfaces_returns_false(self, nb_client):
        vm = MockRecord(100, name="web-1")
        ip = MockRecord(200, address="10.0.0.5/24", assigned_object_id=999)

        nb_client.nb.virtualization.virtual_machines.get.return_value = vm
        nb_client.nb.ipam.ip_addresses.get.return_value = ip
        nb_client.nb.virtualization.interfaces.filter.return_value = []  # No interfaces

        result = nb_client.set_vm_primary_ip(100, 200)

        assert result is False


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


class TestCreateInterface:
    def test_create_interface_success(self, nb_client):
        iface = MockRecord(50, name="eth0")
        nb_client.nb.virtualization.interfaces.create.return_value = iface

        result = nb_client.create_interface({
            "virtual_machine": 100,
            "name": "eth0",
        })

        assert result.id == 50
        # Should set default type
        call_args = nb_client.nb.virtualization.interfaces.create.call_args[0][0]
        assert call_args["type"] == "virtual"

    def test_create_interface_dry_run(self, nb_client_dry_run):
        result = nb_client_dry_run.create_interface({
            "virtual_machine": 100,
            "name": "eth0",
        })

        assert result is not None
        assert result.name == "eth0"


class TestCreateIP:
    def test_create_ip_adds_cidr(self, nb_client):
        nb_client.nb.ipam.ip_addresses.filter.return_value = []
        ip = MockRecord(300, address="10.0.0.5/32")
        nb_client.nb.ipam.ip_addresses.create.return_value = ip

        result = nb_client.create_ip({"address": "10.0.0.5", "interface": 50})

        assert result.id == 300
        call_args = nb_client.nb.ipam.ip_addresses.create.call_args[0][0]
        assert call_args["address"] == "10.0.0.5/32"
        assert call_args["assigned_object_type"] == "virtualization.vminterface"
        assert call_args["assigned_object_id"] == 50

    def test_create_ip_returns_existing(self, nb_client):
        existing = MockRecord(301, address="10.0.0.5/24", assigned_object_id=50)
        nb_client.nb.ipam.ip_addresses.filter.return_value = [existing]

        result = nb_client.create_ip({"address": "10.0.0.5/32", "interface": 50})

        assert result.id == 301
        nb_client.nb.ipam.ip_addresses.create.assert_not_called()

    def test_create_ip_updates_interface_on_existing(self, nb_client):
        existing = MockRecord(301, address="10.0.0.5/24", assigned_object_id=40)
        nb_client.nb.ipam.ip_addresses.filter.return_value = [existing]

        result = nb_client.create_ip({"address": "10.0.0.5/32", "interface": 50})

        assert result.id == 301
        assert existing.assigned_object_id == 50

    def test_create_ip_dry_run(self, nb_client_dry_run):
        result = nb_client_dry_run.create_ip({"address": "10.0.0.5"})
        assert result is None


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


class TestCreateDisk:
    def test_create_disk_success(self, nb_client):
        disk = MockRecord(60, name="boot-disk")
        nb_client.nb.virtualization.virtual_disks = MagicMock()
        nb_client.nb.virtualization.virtual_disks.create.return_value = disk

        result = nb_client.create_disk({"virtual_machine": 100, "size": 50, "name": "boot-disk"})

        assert result.id == 60

    def test_create_disk_dry_run(self, nb_client_dry_run):
        result = nb_client_dry_run.create_disk({"virtual_machine": 100, "size": 50, "name": "boot"})
        assert result is None


class TestImports:
    def test_import_from_module(self):
        from infraverse.providers.netbox import NetBoxClient as NB
        assert NB is NetBoxClient


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
