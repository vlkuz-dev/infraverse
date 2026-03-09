"""Tests for infraverse.sync.vms_networking module."""

from infraverse.sync.vms_networking import update_vm_primary_ip, sync_vm_interfaces
from tests.conftest import MockRecord, make_mock_netbox_client


class TestUpdateVmPrimaryIp:
    """Tests for update_vm_primary_ip."""

    def test_no_interfaces_returns_false(self):
        """Returns False when VM has no network interfaces."""
        netbox = make_mock_netbox_client()
        vm = MockRecord(id=1, name="test-vm", primary_ip4=None)
        yc_vm = {"network_interfaces": []}

        result = update_vm_primary_ip(vm, yc_vm, netbox)

        assert result is False

    def test_prefers_private_ip(self):
        """Private IP is preferred over public for primary."""
        netbox = make_mock_netbox_client()

        existing_ip = MockRecord(
            id=400, address="10.0.0.5/32",
            assigned_object_id=300, assigned_object_type="virtualization.vminterface",
        )
        netbox.nb.ipam.ip_addresses.filter.return_value = [existing_ip]

        vm_iface = MockRecord(id=300, name="eth0")
        netbox.nb.virtualization.interfaces.filter.return_value = [vm_iface]
        netbox.nb.virtualization.virtual_machines.filter.return_value = []

        vm = MockRecord(id=1, name="test-vm", primary_ip4=None)
        yc_vm = {
            "network_interfaces": [
                {
                    "primary_v4_address": "10.0.0.5",
                    "primary_v4_address_one_to_one_nat": "203.0.113.5",
                }
            ]
        }

        result = update_vm_primary_ip(vm, yc_vm, netbox)

        assert result is True
        netbox.set_vm_primary_ip.assert_called_once_with(1, 400, ip_version=4)

    def test_correct_primary_already_set(self):
        """Returns False when VM already has the correct primary IP."""
        netbox = make_mock_netbox_client()
        vm = MockRecord(
            id=1, name="test-vm",
            primary_ip4=MockRecord(address="10.0.0.5/32"),
        )
        yc_vm = {
            "network_interfaces": [{"primary_v4_address": "10.0.0.5"}]
        }

        result = update_vm_primary_ip(vm, yc_vm, netbox)

        assert result is False


class TestSyncVmInterfaces:
    """Tests for sync_vm_interfaces."""

    def test_creates_new_interface(self):
        """New interfaces are created."""
        netbox = make_mock_netbox_client()
        netbox.nb.virtualization.interfaces.filter.return_value = []
        created_iface = MockRecord(id=300, name="eth0")
        netbox.create_interface.return_value = created_iface
        netbox.nb.ipam.ip_addresses.filter.return_value = []

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {
            "network_interfaces": [{"primary_v4_address": "10.0.0.5"}]
        }

        result = sync_vm_interfaces(vm, yc_vm, netbox)

        assert result["interfaces_created"] == 1
        netbox.create_interface.assert_called_once()

    def test_existing_interface_reused(self):
        """Existing interfaces are not re-created."""
        netbox = make_mock_netbox_client()
        existing_iface = MockRecord(id=300, name="eth0")
        netbox.nb.virtualization.interfaces.filter.return_value = [existing_iface]
        netbox.nb.ipam.ip_addresses.filter.return_value = []

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {
            "network_interfaces": [{"primary_v4_address": "10.0.0.5"}]
        }

        result = sync_vm_interfaces(vm, yc_vm, netbox)

        assert result["interfaces_created"] == 0
        netbox.create_interface.assert_not_called()

    def test_creates_ip_for_interface(self):
        """IP addresses are created and attached to interfaces."""
        netbox = make_mock_netbox_client()
        existing_iface = MockRecord(id=300, name="eth0")
        netbox.nb.virtualization.interfaces.filter.return_value = [existing_iface]
        netbox.nb.ipam.ip_addresses.filter.return_value = []
        created_ip = MockRecord(id=400, address="10.0.0.5/32")
        netbox.create_ip.return_value = created_ip

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {
            "network_interfaces": [{"primary_v4_address": "10.0.0.5"}]
        }

        result = sync_vm_interfaces(vm, yc_vm, netbox)

        assert result["ips_created"] == 1
        netbox.create_ip.assert_called_once()

    def test_creates_public_ip(self):
        """Public NAT IPs are created."""
        netbox = make_mock_netbox_client()
        existing_iface = MockRecord(id=300, name="eth0")
        netbox.nb.virtualization.interfaces.filter.return_value = [existing_iface]
        netbox.nb.ipam.ip_addresses.filter.return_value = []
        netbox.create_ip.return_value = MockRecord(id=400, address="203.0.113.1/32")

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {
            "network_interfaces": [
                {"primary_v4_address_one_to_one_nat": "203.0.113.1"}
            ]
        }

        result = sync_vm_interfaces(vm, yc_vm, netbox)

        assert result["ips_created"] == 1

    def test_non_list_interfaces_returns_empty(self):
        """If network_interfaces is not a list, returns empty result."""
        netbox = make_mock_netbox_client()
        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"network_interfaces": "invalid"}

        result = sync_vm_interfaces(vm, yc_vm, netbox)

        assert result == {"interfaces_created": 0, "ips_created": 0, "errors": 0}

    def test_interface_creation_failure_counted(self):
        """Failed interface creation increments error count."""
        netbox = make_mock_netbox_client()
        netbox.nb.virtualization.interfaces.filter.return_value = []
        netbox.create_interface.return_value = None  # creation failed

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"network_interfaces": [{"primary_v4_address": "10.0.0.5"}]}

        result = sync_vm_interfaces(vm, yc_vm, netbox)

        assert result["errors"] == 1
        assert result["interfaces_created"] == 0
