"""Tests for NetBox interface, disk, and IP methods (netbox_interfaces.py mixin)."""

import pytest
from unittest.mock import MagicMock, patch

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

    def test_create_disk_no_virtual_disks_support(self, nb_client):
        # Remove virtual_disks attribute to simulate older NetBox
        del nb_client.nb.virtualization.virtual_disks

        result = nb_client.create_disk({"virtual_machine": 100, "size": 50, "name": "boot"})

        assert result is None

    def test_create_disk_api_error(self, nb_client):
        nb_client.nb.virtualization.virtual_disks = MagicMock()
        nb_client.nb.virtualization.virtual_disks.create.side_effect = Exception("API error")

        result = nb_client.create_disk({"virtual_machine": 100, "size": 50, "name": "boot"})

        assert result is None


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

    def test_create_interface_preserves_explicit_type(self, nb_client):
        iface = MockRecord(51, name="eth1")
        nb_client.nb.virtualization.interfaces.create.return_value = iface

        result = nb_client.create_interface({
            "virtual_machine": 100,
            "name": "eth1",
            "type": "bridge",
        })

        assert result.id == 51
        call_args = nb_client.nb.virtualization.interfaces.create.call_args[0][0]
        assert call_args["type"] == "bridge"

    def test_create_interface_dry_run(self, nb_client_dry_run):
        result = nb_client_dry_run.create_interface({
            "virtual_machine": 100,
            "name": "eth0",
        })

        assert result is not None
        assert result.name == "eth0"

    def test_create_interface_api_error(self, nb_client):
        nb_client.nb.virtualization.interfaces.create.side_effect = Exception("API error")

        result = nb_client.create_interface({"virtual_machine": 100, "name": "eth0"})

        assert result is None


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

    def test_create_ip_with_new_format(self, nb_client):
        nb_client.nb.ipam.ip_addresses.filter.return_value = []
        ip = MockRecord(302, address="10.0.0.6/32")
        nb_client.nb.ipam.ip_addresses.create.return_value = ip

        result = nb_client.create_ip({
            "address": "10.0.0.6",
            "assigned_object_type": "virtualization.vminterface",
            "assigned_object_id": 60,
        })

        assert result.id == 302
        call_args = nb_client.nb.ipam.ip_addresses.create.call_args[0][0]
        assert call_args["assigned_object_id"] == 60

    def test_create_ip_with_description(self, nb_client):
        nb_client.nb.ipam.ip_addresses.filter.return_value = []
        ip = MockRecord(303, address="10.0.0.7/32")
        nb_client.nb.ipam.ip_addresses.create.return_value = ip

        result = nb_client.create_ip({
            "address": "10.0.0.7",
            "interface": 50,
            "description": "primary IP",
        })

        assert result.id == 303
        call_args = nb_client.nb.ipam.ip_addresses.create.call_args[0][0]
        assert call_args["description"] == "primary IP"

    def test_create_ip_api_error(self, nb_client):
        nb_client.nb.ipam.ip_addresses.filter.side_effect = Exception("API error")

        result = nb_client.create_ip({"address": "10.0.0.5", "interface": 50})

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

    def test_api_error(self, nb_client):
        nb_client.nb.virtualization.virtual_machines.get.side_effect = Exception("API error")

        result = nb_client.set_vm_primary_ip(100, 200)

        assert result is False
