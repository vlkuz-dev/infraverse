"""Tests for infraverse.sync.vms_disks module."""

from infraverse.sync.vms_disks import sync_vm_disks
from tests.conftest import MockRecord, make_mock_netbox_client


class TestSyncVmDisks:
    """Tests for sync_vm_disks."""

    def test_creates_new_disk(self):
        """New disks from YC are created in NetBox."""
        netbox = make_mock_netbox_client()
        netbox.nb.virtualization.virtual_disks.filter.return_value = []

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"disks": [{"name": "boot", "size": 10737418240}]}  # 10 GB in bytes

        result = sync_vm_disks(vm, yc_vm, netbox)

        assert result["created"] == 1
        netbox.create_disk.assert_called_once()
        disk_data = netbox.create_disk.call_args[0][0]
        assert disk_data["name"] == "boot"
        assert disk_data["size"] == 10000  # 10 GiB -> 10000 MB (NetBox displays as 10.00 GB)

    def test_unchanged_disk(self):
        """Existing disks with matching size are unchanged."""
        netbox = make_mock_netbox_client()
        existing_disk = MockRecord(id=10, name="boot", size=10000)
        netbox.nb.virtualization.virtual_disks.filter.return_value = [existing_disk]

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"disks": [{"name": "boot", "size": 10737418240}]}

        result = sync_vm_disks(vm, yc_vm, netbox)

        assert result["unchanged"] == 1
        assert result["created"] == 0
        netbox.create_disk.assert_not_called()

    def test_removes_orphaned_disk(self):
        """Disks in NetBox but not in YC are deleted."""
        netbox = make_mock_netbox_client()
        orphan_disk = MockRecord(id=10, name="old-disk", size=5120)
        netbox.nb.virtualization.virtual_disks.filter.return_value = [orphan_disk]

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"disks": []}  # No disks in YC

        result = sync_vm_disks(vm, yc_vm, netbox, remove_orphaned=True)

        assert result["deleted"] == 1
        orphan_disk.delete.assert_called_once()

    def test_no_orphan_removal_when_disabled(self):
        """Orphan removal is skipped when remove_orphaned=False."""
        netbox = make_mock_netbox_client()
        orphan_disk = MockRecord(id=10, name="old-disk", size=5120)
        netbox.nb.virtualization.virtual_disks.filter.return_value = [orphan_disk]

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"disks": []}

        result = sync_vm_disks(vm, yc_vm, netbox, remove_orphaned=False)

        assert result["deleted"] == 0
        orphan_disk.delete.assert_not_called()

    def test_invalid_disk_size_skipped(self):
        """Disks with zero or non-numeric size are skipped."""
        netbox = make_mock_netbox_client()
        netbox.nb.virtualization.virtual_disks.filter.return_value = []

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"disks": [{"name": "bad-disk", "size": 0}]}

        result = sync_vm_disks(vm, yc_vm, netbox)

        assert result["created"] == 0
        netbox.create_disk.assert_not_called()

    def test_no_virtual_disks_support(self):
        """When NetBox doesn't support virtual_disks, returns zeros."""
        netbox = make_mock_netbox_client()
        del netbox.nb.virtualization.virtual_disks

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"disks": [{"name": "boot", "size": 10737418240}]}

        result = sync_vm_disks(vm, yc_vm, netbox)

        assert result == {"created": 0, "deleted": 0, "unchanged": 0}

    def test_disk_with_type_description(self):
        """Disk type is included in description."""
        netbox = make_mock_netbox_client()
        netbox.nb.virtualization.virtual_disks.filter.return_value = []

        vm = MockRecord(id=1, name="test-vm")
        yc_vm = {"disks": [{"name": "boot", "size": 10737418240, "type": "network-ssd"}]}

        sync_vm_disks(vm, yc_vm, netbox)

        disk_data = netbox.create_disk.call_args[0][0]
        assert disk_data["description"] == "Type: network-ssd"
