"""Tests for CloudProvider Protocol and VMInfo dataclass."""

from infraverse.providers.base import CloudProvider, VMInfo


class TestVMInfo:
    """Tests for the VMInfo dataclass."""

    def test_create_with_all_fields(self):
        vm = VMInfo(
            name="test-vm",
            id="vm-123",
            status="active",
            ip_addresses=["10.0.0.1", "192.168.1.1"],
            vcpus=4,
            memory_mb=8192,
            provider="yandex_cloud",
            cloud_name="my-cloud",
            folder_name="my-folder",
        )
        assert vm.name == "test-vm"
        assert vm.id == "vm-123"
        assert vm.status == "active"
        assert vm.ip_addresses == ["10.0.0.1", "192.168.1.1"]
        assert vm.vcpus == 4
        assert vm.memory_mb == 8192
        assert vm.provider == "yandex_cloud"
        assert vm.cloud_name == "my-cloud"
        assert vm.folder_name == "my-folder"

    def test_create_with_required_fields_only(self):
        vm = VMInfo(name="minimal-vm", id="vm-456", status="offline")
        assert vm.name == "minimal-vm"
        assert vm.id == "vm-456"
        assert vm.status == "offline"
        assert vm.ip_addresses == []
        assert vm.vcpus == 0
        assert vm.memory_mb == 0
        assert vm.provider == ""
        assert vm.cloud_name == ""
        assert vm.folder_name == ""

    def test_default_ip_addresses_not_shared(self):
        vm1 = VMInfo(name="vm1", id="1", status="active")
        vm2 = VMInfo(name="vm2", id="2", status="active")
        vm1.ip_addresses.append("10.0.0.1")
        assert vm2.ip_addresses == []

    def test_status_values(self):
        for status in ("active", "offline", "unknown"):
            vm = VMInfo(name="vm", id="1", status=status)
            assert vm.status == status

    def test_equality(self):
        vm1 = VMInfo(name="vm", id="1", status="active", vcpus=2)
        vm2 = VMInfo(name="vm", id="1", status="active", vcpus=2)
        assert vm1 == vm2

    def test_inequality(self):
        vm1 = VMInfo(name="vm", id="1", status="active")
        vm2 = VMInfo(name="vm", id="2", status="active")
        assert vm1 != vm2


class TestCloudProviderProtocol:
    """Tests for the CloudProvider Protocol."""

    def test_class_implementing_protocol(self):
        class FakeProvider:
            def fetch_vms(self) -> list[VMInfo]:
                return [VMInfo(name="fake-vm", id="1", status="active")]

            def get_provider_name(self) -> str:
                return "fake-provider"

        provider = FakeProvider()
        assert isinstance(provider, CloudProvider)
        assert provider.get_provider_name() == "fake-provider"
        vms = provider.fetch_vms()
        assert len(vms) == 1
        assert vms[0].name == "fake-vm"

    def test_class_not_implementing_protocol(self):
        class NotAProvider:
            pass

        obj = NotAProvider()
        assert not isinstance(obj, CloudProvider)
