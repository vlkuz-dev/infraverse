"""Tests for compute_sync_reasons diagnostics."""

from datetime import datetime, timezone

from infraverse.comparison.diagnostics import compute_sync_reasons
from infraverse.comparison.models import VMState
from infraverse.db.models import SyncRun


def _make_sync_run(
    source: str,
    status: str,
    error_message: str | None = None,
    items_found: int = 0,
) -> SyncRun:
    """Create a SyncRun instance without persisting it."""
    run = SyncRun(
        source=source,
        status=status,
        started_at=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        error_message=error_message,
        items_found=items_found,
    )
    if status != "running":
        run.finished_at = datetime(2025, 6, 1, 12, 5, tzinfo=timezone.utc)
    return run


class TestComputeSyncReasons:
    # --- Never ran ---

    def test_never_ran_netbox(self):
        """When netbox sync never ran, reason explains data is unreliable."""
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": None, "zabbix": None})
        reason = state.sync_reasons["in cloud but not in NetBox"]
        assert "не запускался" in reason
        assert "неточным" in reason

    def test_never_ran_zabbix(self):
        """When zabbix sync never ran, reason explains data is unreliable."""
        state = VMState(
            vm_name="vm1", in_cloud=True, in_monitoring=False,
            discrepancies=["in cloud but not in monitoring"],
        )
        compute_sync_reasons([state], {"netbox": None, "zabbix": None})
        reason = state.sync_reasons["in cloud but not in monitoring"]
        assert "не запускалась" in reason
        assert "неточным" in reason

    # --- Failed ---

    def test_failed_netbox(self):
        """When netbox sync failed, reason includes error and warns about stale data."""
        run = _make_sync_run("netbox", "failed", error_message="Connection refused")
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": run, "zabbix": None})
        reason = state.sync_reasons["in cloud but not in NetBox"]
        assert "Connection refused" in reason
        assert "устаревшими" in reason

    def test_failed_zabbix(self):
        """When zabbix sync failed, reason includes error and warns about stale data."""
        run = _make_sync_run("zabbix", "failed", error_message="Timeout")
        state = VMState(
            vm_name="vm1", in_cloud=True, in_monitoring=False,
            discrepancies=["in cloud but not in monitoring"],
        )
        compute_sync_reasons([state], {"netbox": None, "zabbix": run})
        reason = state.sync_reasons["in cloud but not in monitoring"]
        assert "Timeout" in reason
        assert "устаревшими" in reason

    def test_failed_no_error_message(self):
        """When sync failed but no error message, use 'неизвестная ошибка'."""
        run = _make_sync_run("netbox", "failed", error_message=None)
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": run, "zabbix": None})
        reason = state.sync_reasons["in cloud but not in NetBox"]
        assert "неизвестная ошибка" in reason

    # --- Running ---

    def test_running_netbox(self):
        """When netbox sync is currently running."""
        run = _make_sync_run("netbox", "running")
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": run, "zabbix": None})
        reason = state.sync_reasons["in cloud but not in NetBox"]
        assert "выполняется" in reason
        assert "обновиться" in reason

    # --- Success: actionable reasons ---

    def test_success_netbox_shows_time_and_action(self):
        """When netbox sync succeeded, shows timestamp, count, and action."""
        run = _make_sync_run("netbox", "success", items_found=42)
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": run, "zabbix": None})
        reason = state.sync_reasons["in cloud but not in NetBox"]
        assert "42 хостов" in reason
        assert "необходимо создать" in reason
        # Timestamp should be present
        assert "01.06.2025" in reason or "2025" in reason

    def test_success_zabbix_shows_time_and_action(self):
        """When zabbix sync succeeded, shows timestamp, count, and action."""
        run = _make_sync_run("zabbix", "success", items_found=100)
        state = VMState(
            vm_name="vm1", in_cloud=True, in_monitoring=False,
            discrepancies=["in cloud but not in monitoring"],
        )
        compute_sync_reasons([state], {"netbox": None, "zabbix": run})
        reason = state.sync_reasons["in cloud but not in monitoring"]
        assert "100 хостов" in reason
        assert "необходимо подключить" in reason

    def test_success_zero_items_found(self):
        """When sync succeeded but found 0 items, still shows count."""
        run = _make_sync_run("netbox", "success", items_found=0)
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": run, "zabbix": None})
        reason = state.sync_reasons["in cloud but not in NetBox"]
        assert "0 хостов" in reason

    # --- Multiple discrepancies ---

    def test_multiple_discrepancies(self):
        """VM with multiple discrepancies gets reasons for each."""
        netbox_run = _make_sync_run("netbox", "success", items_found=10)
        zabbix_run = _make_sync_run("zabbix", "failed", error_message="Auth error")
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False, in_monitoring=False,
            discrepancies=["in cloud but not in NetBox", "in cloud but not in monitoring"],
        )
        compute_sync_reasons([state], {"netbox": netbox_run, "zabbix": zabbix_run})
        assert "необходимо создать" in state.sync_reasons["in cloud but not in NetBox"]
        assert "Auth error" in state.sync_reasons["in cloud but not in monitoring"]

    # --- Unmapped discrepancies ---

    def test_unmapped_discrepancy_ignored(self):
        """Discrepancies not in the mapping are silently skipped."""
        state = VMState(
            vm_name="vm1", in_netbox=True, in_cloud=False,
            discrepancies=["in NetBox but not in cloud"],
        )
        compute_sync_reasons([state], {"netbox": None, "zabbix": None})
        assert "in NetBox but not in cloud" not in state.sync_reasons

    # --- Cross-system discrepancies ---

    def test_in_netbox_but_not_in_monitoring(self):
        """Discrepancy 'in NetBox but not in monitoring' maps to zabbix."""
        run = _make_sync_run("zabbix", "success", items_found=50)
        state = VMState(
            vm_name="vm1", in_netbox=True, in_monitoring=False,
            discrepancies=["in NetBox but not in monitoring"],
        )
        compute_sync_reasons([state], {"netbox": None, "zabbix": run})
        reason = state.sync_reasons["in NetBox but not in monitoring"]
        assert "необходимо подключить" in reason

    def test_in_monitoring_but_not_in_netbox(self):
        """Discrepancy 'in monitoring but not in NetBox' maps to netbox."""
        run = _make_sync_run("netbox", "success", items_found=30)
        state = VMState(
            vm_name="vm1", in_monitoring=True, in_netbox=False,
            discrepancies=["in monitoring but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": run, "zabbix": None})
        reason = state.sync_reasons["in monitoring but not in NetBox"]
        assert "необходимо создать" in reason

    # --- Edge cases ---

    def test_no_discrepancies_no_reasons(self):
        """VM with no discrepancies gets empty sync_reasons."""
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=True, in_monitoring=True,
            discrepancies=[],
        )
        compute_sync_reasons([state], {"netbox": None, "zabbix": None})
        assert state.sync_reasons == {}

    def test_multiple_vms(self):
        """All VMs in the list get annotated."""
        run = _make_sync_run("netbox", "success", items_found=5)
        states = [
            VMState(vm_name="vm1", in_cloud=True, in_netbox=False,
                    discrepancies=["in cloud but not in NetBox"]),
            VMState(vm_name="vm2", in_cloud=True, in_netbox=False,
                    discrepancies=["in cloud but not in NetBox"]),
        ]
        compute_sync_reasons(states, {"netbox": run, "zabbix": None})
        for s in states:
            assert "in cloud but not in NetBox" in s.sync_reasons
            assert "необходимо создать" in s.sync_reasons["in cloud but not in NetBox"]


class TestPerVmSyncErrors:
    """Tests for per-VM sync error display from SyncEngine."""

    def test_vm_sync_error_overrides_generic_reason(self):
        """When VM has a sync error, it takes priority over SyncRun reason."""
        run = _make_sync_run("netbox", "success", items_found=10)
        state = VMState(
            vm_name="broken-vm", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        vm_errors = {"broken-vm": "RequestError: 400 duplicate key"}
        compute_sync_reasons([state], {"netbox": run, "zabbix": None}, vm_errors)
        reason = state.sync_reasons["in cloud but not in NetBox"]
        assert "Ошибка синхронизации в NetBox" in reason
        assert "duplicate key" in reason

    def test_vm_without_error_gets_generic_reason(self):
        """VM without sync error still gets the SyncRun-based reason."""
        run = _make_sync_run("netbox", "success", items_found=10)
        state = VMState(
            vm_name="ok-vm", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        vm_errors = {"other-vm": "some error"}
        compute_sync_reasons([state], {"netbox": run, "zabbix": None}, vm_errors)
        assert "необходимо создать" in state.sync_reasons["in cloud but not in NetBox"]

    def test_vm_error_only_applies_to_netbox_discrepancy(self):
        """VM sync error only applies to NetBox-related discrepancies, not monitoring."""
        run = _make_sync_run("zabbix", "success", items_found=5)
        state = VMState(
            vm_name="broken-vm", in_cloud=True, in_monitoring=False,
            discrepancies=["in cloud but not in monitoring"],
        )
        vm_errors = {"broken-vm": "NetBox API error"}
        compute_sync_reasons([state], {"netbox": None, "zabbix": run}, vm_errors)
        # Monitoring discrepancy should use zabbix SyncRun, not VM error
        reason = state.sync_reasons["in cloud but not in monitoring"]
        assert "необходимо подключить" in reason

    def test_vm_error_with_multiple_discrepancies(self):
        """VM with both NetBox and monitoring discrepancies gets mixed reasons."""
        netbox_run = _make_sync_run("netbox", "success", items_found=10)
        zabbix_run = _make_sync_run("zabbix", "success", items_found=5)
        state = VMState(
            vm_name="broken-vm", in_cloud=True, in_netbox=False, in_monitoring=False,
            discrepancies=["in cloud but not in NetBox", "in cloud but not in monitoring"],
        )
        vm_errors = {"broken-vm": "pynetbox error: 500"}
        compute_sync_reasons(
            [state], {"netbox": netbox_run, "zabbix": zabbix_run}, vm_errors,
        )
        # NetBox discrepancy should use VM error
        assert "pynetbox error: 500" in state.sync_reasons["in cloud but not in NetBox"]
        # Monitoring discrepancy should use SyncRun
        assert "необходимо подключить" in state.sync_reasons["in cloud but not in monitoring"]

    def test_empty_vm_errors_dict(self):
        """Empty vm_errors dict has no effect."""
        run = _make_sync_run("netbox", "success", items_found=10)
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": run, "zabbix": None}, {})
        assert "необходимо создать" in state.sync_reasons["in cloud but not in NetBox"]

    def test_none_vm_errors(self):
        """None vm_errors has no effect (backward compat)."""
        run = _make_sync_run("netbox", "success", items_found=10)
        state = VMState(
            vm_name="vm1", in_cloud=True, in_netbox=False,
            discrepancies=["in cloud but not in NetBox"],
        )
        compute_sync_reasons([state], {"netbox": run, "zabbix": None}, None)
        assert "необходимо создать" in state.sync_reasons["in cloud but not in NetBox"]
