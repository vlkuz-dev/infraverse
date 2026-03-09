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


class TestEnsureSite:
    def test_finds_existing_site_by_name(self, nb_client):
        nb_client._sync_tag_id = 1  # Pre-set to avoid tag creation
        site = MockRecord(5, name="ru-central1-a", slug="ru-central1-a",
                          description="old", status="active", tags=[])
        nb_client.nb.dcim.sites.get.return_value = site

        result = nb_client.ensure_site("ru-central1-a")

        assert result == 5

    def test_creates_site_when_not_found(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.dcim.sites.get.return_value = None
        new_site = MockRecord(6, name="ru-central1-a")
        nb_client.nb.dcim.sites.create.return_value = new_site

        result = nb_client.ensure_site("ru-central1-a")

        assert result == 6
        call_args = nb_client.nb.dcim.sites.create.call_args[0][0]
        assert call_args["name"] == "ru-central1-a"
        assert call_args["slug"] == "ru-central1-a"
        assert call_args["status"] == "active"
        assert call_args["tags"] == [1]

    def test_uses_zone_name_when_provided(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.dcim.sites.get.return_value = None
        new_site = MockRecord(7, name="Zone A")
        nb_client.nb.dcim.sites.create.return_value = new_site

        result = nb_client.ensure_site("ru-central1-a", zone_name="Zone A")

        assert result == 7
        call_args = nb_client.nb.dcim.sites.create.call_args[0][0]
        assert call_args["name"] == "Zone A"
        # slug still derived from zone_id
        assert call_args["slug"] == "ru-central1-a"

    def test_dry_run_returns_mock_id(self, nb_client_dry_run):
        nb_client_dry_run.nb.dcim.sites.get.return_value = None

        result = nb_client_dry_run.ensure_site("ru-central1-a")

        assert result == 1
        nb_client_dry_run.nb.dcim.sites.create.assert_not_called()

    def test_handles_duplicate_slug_error(self, nb_client):
        nb_client._sync_tag_id = 1
        # First get returns None, create throws duplicate slug error
        nb_client.nb.dcim.sites.get.side_effect = [None, None, MockRecord(8, name="ru-central1-a")]
        nb_client.nb.dcim.sites.create.side_effect = Exception("400 slug already exists")

        result = nb_client.ensure_site("ru-central1-a")

        assert result == 8


class TestEnsureClusterType:
    def test_returns_cached_type(self, nb_client):
        nb_client._cluster_type_id = 99
        result = nb_client.ensure_cluster_type()
        assert result == 99

    def test_finds_existing_by_name(self, nb_client):
        nb_client._sync_tag_id = 1
        ct = MockRecord(3, name="yandex-cloud", slug="yandex-cloud",
                        description="Yandex Cloud Platform", tags=[])
        nb_client.nb.virtualization.cluster_types.get.return_value = ct

        result = nb_client.ensure_cluster_type()

        assert result == 3
        assert nb_client._cluster_type_id == 3

    def test_creates_when_not_found(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client.nb.virtualization.cluster_types.get.return_value = None
        new_ct = MockRecord(4, name="yandex-cloud")
        nb_client.nb.virtualization.cluster_types.create.return_value = new_ct

        result = nb_client.ensure_cluster_type()

        assert result == 4


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


class TestSafeUpdateObject:
    def test_updates_changed_fields(self, nb_client):
        obj = MockRecord(1, name="old-name", status="inactive")
        result = nb_client._safe_update_object(obj, {"name": "new-name", "status": "active"})
        assert result is True
        assert obj.name == "new-name"
        obj.save.assert_called_once()

    def test_no_update_when_same(self, nb_client):
        obj = MockRecord(1, name="same")
        result = nb_client._safe_update_object(obj, {"name": "same"})
        assert result is False
        obj.save.assert_not_called()

    def test_empty_updates_returns_false(self, nb_client):
        obj = MockRecord(1, name="test")
        result = nb_client._safe_update_object(obj, {})
        assert result is False

    def test_dry_run_returns_false(self, nb_client_dry_run):
        obj = MockRecord(1, name="old")
        result = nb_client_dry_run._safe_update_object(obj, {"name": "new"})
        assert result is False

    def test_handles_choice_item_comparison(self, nb_client):
        """ChoiceItem objects (e.g., status) are compared by .value."""
        class MockChoiceItem:
            def __init__(self, value):
                self.value = value
        obj = MockRecord(1, name="test", status=MockChoiceItem("active"))
        result = nb_client._safe_update_object(obj, {"status": "active"})
        assert result is False
        obj.save.assert_not_called()

    def test_updates_choice_item_when_different(self, nb_client):
        """ChoiceItem objects trigger update when value differs."""
        class MockChoiceItem:
            def __init__(self, value):
                self.value = value
        obj = MockRecord(1, name="test", status=MockChoiceItem("planned"))
        result = nb_client._safe_update_object(obj, {"status": "active"})
        assert result is True
        obj.save.assert_called_once()


class TestEnsureCluster:
    def test_finds_existing_cluster_by_new_name(self, nb_client):
        """Cluster found by new name format (cloud/folder) — no migration."""
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        cluster = MockRecord(10, name="my-cloud/prod", tags=[],
                             type=MockRecord(2), site=None,
                             comments="Folder ID: folder1")
        nb_client.nb.virtualization.clusters.get.return_value = cluster

        result = nb_client.ensure_cluster("prod", "folder1", "my-cloud")

        assert result == 10

    def test_finds_existing_cluster_by_old_name_and_migrates(self, nb_client):
        """Cluster found by old name (folder only) via filter() — renamed to new format."""
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        old_cluster = MockRecord(15, name="prod-devops", tags=[],
                                 type=MockRecord(2), site=None, comments="")

        # New name and slug lookups return None
        def get_side_effect(**kwargs):
            return None

        nb_client.nb.virtualization.clusters.get.side_effect = get_side_effect
        # Old name fallback uses filter() instead of get()
        nb_client.nb.virtualization.clusters.filter.return_value = [old_cluster]

        result = nb_client.ensure_cluster("prod-devops", "b1gn93aeri4145duf1qt", "grand-trade")

        assert result == 15
        # Should rename cluster to new format
        assert old_cluster.name == "grand-trade/prod-devops"
        assert old_cluster.slug == "grand-trade-prod-devops"
        old_cluster.save.assert_called()
        # Verify filter was called with old name
        nb_client.nb.virtualization.clusters.filter.assert_called_with(name="prod-devops")

    def test_finds_existing_cluster_by_slug(self, nb_client):
        """Cluster found by slug when name lookup fails."""
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        cluster = MockRecord(20, name="grand-trade/infra", slug="grand-trade-infra",
                             tags=[], type=MockRecord(2), site=None, comments="")

        def get_side_effect(**kwargs):
            if kwargs.get("name") == "grand-trade/infra":
                return None  # name lookup fails
            if kwargs.get("slug") == "grand-trade-infra":
                return cluster  # slug lookup succeeds
            return None

        nb_client.nb.virtualization.clusters.get.side_effect = get_side_effect

        result = nb_client.ensure_cluster("infra", "folder-id", "grand-trade")

        assert result == 20

    def test_creates_cluster_when_not_found(self, nb_client):
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        nb_client.nb.virtualization.clusters.get.return_value = None
        nb_client.nb.virtualization.clusters.filter.return_value = []
        new_cluster = MockRecord(11, name="my-cloud/staging")
        nb_client.nb.virtualization.clusters.create.return_value = new_cluster

        result = nb_client.ensure_cluster("staging", "folder2", "my-cloud", site_id=5)

        assert result == 11
        call_args = nb_client.nb.virtualization.clusters.create.call_args[0][0]
        assert call_args["name"] == "my-cloud/staging"
        assert call_args["type"] == 2
        assert call_args["site"] == 5

    def test_creates_cluster_without_cloud_name(self, nb_client):
        """When cloud_name is empty, uses folder_name only — no fallback needed."""
        nb_client._sync_tag_id = 1
        nb_client._cluster_type_id = 2
        nb_client.nb.virtualization.clusters.get.return_value = None
        new_cluster = MockRecord(12, name="standalone")
        nb_client.nb.virtualization.clusters.create.return_value = new_cluster

        result = nb_client.ensure_cluster("standalone", "folder3", "")

        assert result == 12
        call_args = nb_client.nb.virtualization.clusters.create.call_args[0][0]
        assert call_args["name"] == "standalone"

    def test_dry_run_not_found(self, nb_client_dry_run):
        """Dry-run when cluster doesn't exist — returns mock ID."""
        nb_client_dry_run.nb.virtualization.clusters.get.return_value = None
        nb_client_dry_run.nb.virtualization.clusters.filter.return_value = []

        result = nb_client_dry_run.ensure_cluster("prod", "f1", "cloud1")

        assert result == 1

    def test_dry_run_found_by_old_name(self, nb_client_dry_run):
        """Dry-run finds cluster by old name via filter() — returns real ID, no rename."""
        nb_client_dry_run._sync_tag_id = 1
        nb_client_dry_run._cluster_type_id = 2
        old_cluster = MockRecord(25, name="prod", tags=[],
                                 type=MockRecord(2), site=None, comments="")

        # New name and slug lookups return None
        def get_side_effect(**kwargs):
            return None

        nb_client_dry_run.nb.virtualization.clusters.get.side_effect = get_side_effect
        # Old name fallback uses filter()
        nb_client_dry_run.nb.virtualization.clusters.filter.return_value = [old_cluster]

        result = nb_client_dry_run.ensure_cluster("prod", "f1", "cloud1")

        assert result == 25
        # Dry-run should NOT rename
        assert old_cluster.name == "prod"
        old_cluster.save.assert_not_called()


class TestEnsurePlatform:
    def test_finds_existing_platform(self, nb_client):
        platform = MockRecord(5, name="Ubuntu 22.04", slug="ubuntu-22-04")
        nb_client.nb.dcim.platforms.get.return_value = platform

        result = nb_client.ensure_platform("ubuntu-22-04")

        assert result == 5
        nb_client.nb.dcim.platforms.get.assert_called_with(slug="ubuntu-22-04")

    def test_creates_platform_when_not_found(self, nb_client):
        nb_client.nb.dcim.platforms.get.return_value = None
        new_platform = MockRecord(6, name="windows-2022", slug="windows-2022")
        nb_client.nb.dcim.platforms.create.return_value = new_platform

        result = nb_client.ensure_platform("windows-2022", "Windows Server 2022")

        assert result == 6
        call_args = nb_client.nb.dcim.platforms.create.call_args[0][0]
        assert call_args["name"] == "Windows Server 2022"
        assert call_args["slug"] == "windows-2022"

    def test_dry_run(self, nb_client_dry_run):
        nb_client_dry_run.nb.dcim.platforms.get.return_value = None

        result = nb_client_dry_run.ensure_platform("linux")

        assert result == 1
        nb_client_dry_run.nb.dcim.platforms.create.assert_not_called()

    def test_slug_used_as_name_when_no_name(self, nb_client):
        nb_client.nb.dcim.platforms.get.return_value = None
        new_platform = MockRecord(7, name="linux", slug="linux")
        nb_client.nb.dcim.platforms.create.return_value = new_platform

        result = nb_client.ensure_platform("linux")

        assert result == 7
        call_args = nb_client.nb.dcim.platforms.create.call_args[0][0]
        assert call_args["name"] == "linux"


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
