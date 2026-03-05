"""Tests for comparison data models."""

from netbox_sync.comparison.models import ComparisonResult, VMState


class TestVMState:
    def test_defaults(self):
        state = VMState(vm_name="test-vm")
        assert state.vm_name == "test-vm"
        assert state.in_cloud is False
        assert state.in_netbox is False
        assert state.in_monitoring is False
        assert state.cloud_provider is None
        assert state.discrepancies == []

    def test_all_present(self):
        state = VMState(
            vm_name="web-01",
            in_cloud=True,
            in_netbox=True,
            in_monitoring=True,
            cloud_provider="yandex-cloud",
        )
        assert state.in_cloud is True
        assert state.in_netbox is True
        assert state.in_monitoring is True
        assert state.cloud_provider == "yandex-cloud"

    def test_discrepancies_list(self):
        state = VMState(
            vm_name="orphan-vm",
            in_cloud=True,
            discrepancies=["in cloud but not in NetBox"],
        )
        assert len(state.discrepancies) == 1
        assert "in cloud but not in NetBox" in state.discrepancies


class TestComparisonResult:
    def test_defaults(self):
        result = ComparisonResult()
        assert result.all_vms == []
        assert result.summary == {}

    def test_with_data(self):
        states = [
            VMState(vm_name="vm-1", in_cloud=True, in_netbox=True, in_monitoring=True),
            VMState(vm_name="vm-2", in_cloud=True),
        ]
        summary = {"total": 2, "in_sync": 1, "with_discrepancies": 1}
        result = ComparisonResult(all_vms=states, summary=summary)
        assert len(result.all_vms) == 2
        assert result.summary["total"] == 2
