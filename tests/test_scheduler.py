"""Tests for infraverse.scheduler module."""

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from infraverse.config import Config
from infraverse.config_file import InfraverseConfig, MonitoringExclusionRule, NetBoxConfig, TenantConfig, CloudAccountConfig
from infraverse.scheduler import SchedulerService


def _make_config(**overrides):
    """Create a mock config with sensible defaults."""
    config = MagicMock()
    config.yc_token = "test-token"
    config.vcd_configured = False
    config.zabbix_configured = False
    config.netbox_url = None
    config.netbox_token = None
    for k, v in overrides.items():
        setattr(config, k, v)
    return config


def _make_session_factory(session=None):
    """Create a mock session factory."""
    if session is None:
        session = MagicMock()
    factory = MagicMock(return_value=session)
    return factory


class TestSchedulerServiceInit:
    def test_initial_state(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        assert svc._running is False
        assert svc._last_result is None
        assert svc._last_run_time is None

    def test_stores_session_factory_and_config(self):
        sf = _make_session_factory()
        cfg = _make_config()
        svc = SchedulerService(sf, cfg)
        assert svc._session_factory is sf
        assert svc._config is cfg


class TestStartStop:
    def test_start_sets_running(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.start(interval_minutes=30)
        try:
            assert svc._running is True
        finally:
            svc.stop()

    def test_stop_clears_running(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.start(interval_minutes=30)
        svc.stop()
        assert svc._running is False

    def test_stop_when_not_started_is_noop(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.stop()  # should not raise
        assert svc._running is False

    def test_start_creates_ingestion_job(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.start(interval_minutes=15)
        try:
            job = svc._scheduler.get_job("ingestion")
            assert job is not None
        finally:
            svc.stop()

    def test_stop_shuts_down_scheduler(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.start(interval_minutes=30)
        svc.stop()
        assert svc._scheduler.running is False

    def test_job_has_max_instances_1(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.start(interval_minutes=30)
        try:
            job = svc._scheduler.get_job("ingestion")
            assert job.max_instances == 1
        finally:
            svc.stop()

    def test_job_has_coalesce_true(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.start(interval_minutes=30)
        try:
            job = svc._scheduler.get_job("ingestion")
            assert job.coalesce is True
        finally:
            svc.stop()


class TestJobOverlapPrevention:
    """Tests for scheduler job overlap prevention."""

    def test_init_creates_job_lock(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        assert isinstance(svc._job_lock, type(threading.Lock()))

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_run_ingestion_acquires_and_releases_lock(self, mock_cycle):
        mock_cycle.return_value = {}
        svc = SchedulerService(_make_session_factory(), _make_config())

        assert not svc._job_lock.locked()
        svc._run_ingestion()
        assert not svc._job_lock.locked()

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_lock_released_on_error(self, mock_cycle):
        mock_cycle.side_effect = RuntimeError("boom")
        svc = SchedulerService(_make_session_factory(), _make_config())

        svc._run_ingestion()
        assert not svc._job_lock.locked()

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_skips_when_lock_held(self, mock_cycle):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._job_lock.acquire()
        try:
            svc._run_ingestion()
            mock_cycle.assert_not_called()
        finally:
            svc._job_lock.release()

    def test_trigger_now_returns_already_running_when_lock_held(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._run_ingestion = MagicMock()
        svc.start(interval_minutes=60)
        try:
            svc._job_lock.acquire()
            try:
                result = svc.trigger_now()
                assert result == "already_running"
            finally:
                svc._job_lock.release()
        finally:
            svc.stop()

    def test_trigger_now_returns_triggered_when_no_lock(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._run_ingestion = MagicMock()
        svc.start(interval_minutes=60)
        try:
            result = svc.trigger_now()
            assert result == "triggered"
        finally:
            svc.stop()

    def test_trigger_now_without_scheduler_returns_triggered(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._run_ingestion = MagicMock()
        svc._scheduler.start()
        svc._running = True
        try:
            result = svc.trigger_now()
            assert result == "triggered"
        finally:
            svc._scheduler.shutdown(wait=False)

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_concurrent_ingestion_blocked(self, mock_cycle):
        """Simulate concurrent execution: second call is blocked while first holds lock."""
        started = threading.Event()

        def slow_cycle(*args, **kwargs):
            started.set()  # Signal that we're inside the cycle
            time.sleep(0.3)
            return {}

        mock_cycle.side_effect = slow_cycle
        svc = SchedulerService(_make_session_factory(), _make_config())

        t1 = threading.Thread(target=svc._run_ingestion)
        t1.start()
        started.wait(timeout=5)  # Wait until first thread holds the lock

        # Second call should be rejected immediately
        svc._run_ingestion()
        t1.join(timeout=5)

        assert mock_cycle.call_count == 1
        assert not svc._job_lock.locked()


class TestTriggerNow:
    def test_trigger_now_modifies_existing_job(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        # Mock _run_ingestion BEFORE start() so APScheduler captures the mock
        svc._run_ingestion = MagicMock()
        svc.start(interval_minutes=60)
        try:
            svc.trigger_now()
            # Trigger sets next_run_time to now - the job still exists
            job = svc._scheduler.get_job("ingestion")
            assert job is not None
        finally:
            svc.stop()

    def test_trigger_now_without_existing_job_adds_manual(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        # Mock _run_ingestion BEFORE starting so APScheduler captures the mock
        svc._run_ingestion = MagicMock()
        svc._scheduler.start()
        svc._running = True
        try:
            svc.trigger_now()
            # Give the background thread time to pick up the job
            time.sleep(0.2)
            # The manual job fires immediately and gets consumed; verify _run_ingestion was called
            svc._run_ingestion.assert_called()
        finally:
            svc._scheduler.shutdown(wait=False)

    @patch("infraverse.scheduler.run_ingestion_cycle")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_trigger_now_executes_ingestion(self, mock_repo_cls, mock_ingestor_cls, mock_cycle):
        mock_cycle.return_value = {"test": "success"}

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config())
        svc.start(interval_minutes=60)
        try:
            svc.trigger_now()
            # Give the background thread time to execute
            time.sleep(0.5)
            mock_cycle.assert_called_once()
            assert svc._last_result == {"test": "success"}
            assert svc._last_run_time is not None
        finally:
            svc.stop()


class TestGetStatus:
    def test_status_when_idle(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        status = svc.get_status()
        assert status["running"] is False
        assert status["next_run_time"] is None
        assert status["last_run_time"] is None
        assert status["last_result"] is None

    def test_status_when_running(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.start(interval_minutes=30)
        try:
            status = svc.get_status()
            assert status["running"] is True
            assert status["next_run_time"] is not None
            assert status["last_run_time"] is None
            assert status["last_result"] is None
        finally:
            svc.stop()

    def test_status_after_successful_run(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._last_result = {"account1": "success"}
        svc._last_run_time = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        svc._running = True

        status = svc.get_status()
        assert status["running"] is True
        assert status["last_run_time"] == "2025-01-15T10:30:00+00:00"
        assert status["last_result"] == {"account1": "success"}

    def test_status_after_failed_run(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._last_result = {"error": "connection failed"}
        svc._last_run_time = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        status = svc.get_status()
        assert status["last_result"] == {"error": "connection failed"}
        assert status["last_run_time"] is not None

    def test_status_after_stop(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        svc.start(interval_minutes=30)
        svc.stop()
        status = svc.get_status()
        assert status["running"] is False


class TestRunIngestion:
    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_successful_ingestion(self, mock_cycle):
        mock_cycle.return_value = {"yc": "success"}

        session = MagicMock()
        cfg = _make_config()
        svc = SchedulerService(_make_session_factory(session), cfg)
        svc._run_ingestion()

        mock_cycle.assert_called_once_with(
            session, infraverse_config=None, legacy_config=cfg,
        )
        assert svc._last_result == {"yc": "success"}
        assert svc._last_run_time is not None
        session.close.assert_called_once()

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_ingestion_error_captured(self, mock_cycle):
        mock_cycle.side_effect = RuntimeError("db connection lost")

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config())
        svc._run_ingestion()  # should not raise

        assert svc._last_result == {"error": "db connection lost"}
        assert svc._last_run_time is not None
        session.close.assert_called_once()

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_session_closed_on_error(self, mock_cycle):
        mock_cycle.side_effect = RuntimeError("boom")

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config())
        svc._run_ingestion()

        session.close.assert_called_once()

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_ingestion_with_no_providers(self, mock_cycle):
        mock_cycle.return_value = {}

        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._run_ingestion()

        assert svc._last_result == {}


class TestResolveNetboxConfig:
    """Tests for _resolve_netbox_config helper method."""

    def test_config_file_mode(self):
        nb = NetBoxConfig(url="https://netbox.yaml.com", token="yaml-token")
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]}, netbox=nb)
        cfg = _make_config()
        svc = SchedulerService(_make_session_factory(), cfg, infraverse_config=ic)

        url, token, dry_run = svc._resolve_netbox_config()
        assert url == "https://netbox.yaml.com"
        assert token == "yaml-token"
        assert dry_run is False

    def test_env_var_mode_with_real_config(self):
        cfg = _make_real_config(netbox_url="https://netbox.env.com", netbox_token="env-token", dry_run=True)
        svc = SchedulerService(_make_session_factory(), cfg)

        url, token, dry_run = svc._resolve_netbox_config()
        assert url == "https://netbox.env.com"
        assert token == "env-token"
        assert dry_run is True

    def test_fallback_simple_namespace(self):
        cfg = SimpleNamespace(netbox_url="https://ns.com", netbox_token="ns-token")
        svc = SchedulerService(_make_session_factory(), cfg)

        url, token, dry_run = svc._resolve_netbox_config()
        assert url == "https://ns.com"
        assert token == "ns-token"
        assert dry_run is False

    def test_returns_none_when_mock_config(self):
        cfg = _make_config()
        svc = SchedulerService(_make_session_factory(), cfg)

        url, token, dry_run = svc._resolve_netbox_config()
        assert url is None
        assert token is None

    def test_config_file_takes_precedence_over_env(self):
        nb = NetBoxConfig(url="https://yaml.com", token="yaml-t")
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]}, netbox=nb)
        cfg = _make_real_config(netbox_url="https://env.com", netbox_token="env-t")
        svc = SchedulerService(_make_session_factory(), cfg, infraverse_config=ic)

        url, token, _ = svc._resolve_netbox_config()
        assert url == "https://yaml.com"
        assert token == "yaml-t"


def _make_infraverse_config(tenants=None, monitoring=None, monitoring_exclusions=None, netbox=None):
    """Create an InfraverseConfig for testing."""
    t = {}
    for tname, accounts in (tenants or {}).items():
        accs = [
            CloudAccountConfig(name=a[0], provider=a[1], credentials=a[2] if len(a) > 2 else {})
            for a in accounts
        ]
        t[tname] = TenantConfig(name=tname, cloud_accounts=accs)
    return InfraverseConfig(
        tenants=t, monitoring=monitoring,
        monitoring_exclusions=monitoring_exclusions or [],
        netbox=netbox,
    )


class TestSchedulerWithInfraverseConfig:
    """Tests for SchedulerService with InfraverseConfig (config-file mode)."""

    def test_stores_infraverse_config(self):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        svc = SchedulerService(_make_session_factory(), _make_config(), infraverse_config=ic)
        assert svc._infraverse_config is ic

    def test_infraverse_config_defaults_to_none(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        assert svc._infraverse_config is None

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_run_ingestion_passes_infraverse_config(self, mock_cycle):
        mock_cycle.return_value = {}
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})

        session = MagicMock()
        cfg = _make_config()
        svc = SchedulerService(_make_session_factory(session), cfg, infraverse_config=ic)
        svc._run_ingestion()

        mock_cycle.assert_called_once_with(session, infraverse_config=ic, legacy_config=cfg)

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_run_ingestion_without_infraverse_config(self, mock_cycle):
        mock_cycle.return_value = {}

        cfg = _make_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        svc._run_ingestion()

        call_kwargs = mock_cycle.call_args.kwargs
        assert call_kwargs["infraverse_config"] is None
        assert call_kwargs["legacy_config"] is cfg




class TestSchedulerMultiTenant:
    """Tests for scheduler multi-tenant ingestion via run_ingestion_cycle.

    Detailed multi-tenant provider building and filtering tests are in
    tests/sync/test_orchestrator.py. These tests verify the scheduler
    correctly delegates to run_ingestion_cycle.
    """

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_multiple_tenants_delegates_to_orchestrator(self, mock_cycle):
        mock_cycle.return_value = {"acme": "ok", "beta": "ok"}

        ic = _make_infraverse_config(tenants={
            "acme": [("acme-yc", "yandex_cloud", {"token": "t1"})],
            "beta": [("beta-yc", "yandex_cloud", {"token": "t2"})],
        })

        session = MagicMock()
        cfg = _make_config()
        svc = SchedulerService(_make_session_factory(session), cfg, infraverse_config=ic)
        svc._run_ingestion()

        mock_cycle.assert_called_once_with(session, infraverse_config=ic, legacy_config=cfg)
        assert svc._last_result["acme"] == "ok"
        assert svc._last_result["beta"] == "ok"


def _make_real_config(**overrides):
    """Create a real Config instance for testing."""
    defaults = dict(
        yc_token="test-token",
        netbox_url="https://netbox.example.com",
        netbox_token="nb-token",
        dry_run=False,
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestRunNetboxSync:
    """Tests for _run_netbox_sync method."""

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_runs_when_config_is_real(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine = MagicMock()
        mock_engine.run.return_value = {"vms_synced": 5}
        mock_engine_cls.return_value = mock_engine

        cfg = _make_real_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        result = svc._run_netbox_sync()

        assert result == {"vms_synced": 5}
        mock_engine_cls.assert_called_once()
        mock_engine.run.assert_called_once()

    def test_skipped_when_config_is_mock(self):
        cfg = _make_config()  # MagicMock, not a real Config
        svc = SchedulerService(_make_session_factory(), cfg)
        result = svc._run_netbox_sync()

        assert result is None

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_runs_when_config_is_simple_namespace_with_netbox(self, mock_engine_cls, mock_nb_cls, mock_build):
        """SimpleNamespace with netbox credentials now correctly triggers sync."""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        cfg = SimpleNamespace(yc_token="t", netbox_url="u", netbox_token="n")
        svc = SchedulerService(_make_session_factory(), cfg)
        result = svc._run_netbox_sync()

        assert result == {}
        mock_engine.run.assert_called_once()

    def test_skipped_when_config_is_simple_namespace_no_netbox(self):
        cfg = SimpleNamespace(yc_token="t")
        svc = SchedulerService(_make_session_factory(), cfg)
        result = svc._run_netbox_sync()

        assert result is None

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_failure_returns_error_dict(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine_cls.side_effect = RuntimeError("netbox unreachable")

        cfg = _make_real_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        result = svc._run_netbox_sync()

        assert result == {"error": "netbox unreachable"}

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_run_failure_returns_error_dict(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine = MagicMock()
        mock_engine.run.side_effect = RuntimeError("sync failed")
        mock_engine_cls.return_value = mock_engine

        cfg = _make_real_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        result = svc._run_netbox_sync()

        assert result == {"error": "sync failed"}

    @patch("infraverse.scheduler.run_ingestion_cycle")
    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_ingestion_result_includes_netbox_sync(self, mock_repo_cls, mock_ingestor_cls, mock_engine_cls, mock_nb_cls, mock_build, mock_cycle):
        mock_cycle.return_value = {"yc": "ok"}

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor_cls.return_value = mock_ingestor

        mock_engine = MagicMock()
        mock_engine.run.return_value = {"vms_synced": 3}
        mock_engine_cls.return_value = mock_engine

        cfg = _make_real_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        svc._run_ingestion()

        assert svc._last_result["yc"] == "ok"
        assert svc._last_result["netbox_sync"] == {"vms_synced": 3}

    @patch("infraverse.scheduler.run_ingestion_cycle")
    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_netbox_failure_does_not_affect_ingestion_result(self, mock_repo_cls, mock_ingestor_cls, mock_engine_cls, mock_nb_cls, mock_build, mock_cycle):
        mock_cycle.return_value = {"yc": "ok"}

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor_cls.return_value = mock_ingestor

        mock_engine_cls.side_effect = RuntimeError("netbox down")

        cfg = _make_real_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        svc._run_ingestion()

        assert svc._last_result["yc"] == "ok"
        assert svc._last_result["netbox_sync"] == {"error": "netbox down"}

    @patch("infraverse.scheduler.run_ingestion_cycle")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_no_netbox_sync_key_when_config_is_mock(self, mock_repo_cls, mock_ingestor_cls, mock_cycle):
        mock_cycle.return_value = {"yc": "ok"}

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor_cls.return_value = mock_ingestor

        cfg = _make_config()  # MagicMock
        svc = SchedulerService(_make_session_factory(), cfg)
        svc._run_ingestion()

        assert svc._last_result == {"yc": "ok"}
        assert "netbox_sync" not in svc._last_result


class TestRunNetboxSyncConfigFileMode:
    """Tests for _run_netbox_sync in config-file mode using SyncEngine."""

    def _make_account(self, name="acme-yc", provider_type="yandex_cloud", is_active=True, config=None):
        account = MagicMock()
        account.name = name
        account.provider_type = provider_type
        account.is_active = is_active
        account.config = config or {"token": "t1"}
        return account

    def _make_svc(self, netbox_url="https://netbox.example.com", netbox_token="nb-token"):
        nb = NetBoxConfig(url=netbox_url, token=netbox_token) if netbox_url and netbox_token else None
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]}, netbox=nb)
        cfg = SimpleNamespace(netbox_url=None, netbox_token=None)
        return SchedulerService(_make_session_factory(), cfg, infraverse_config=ic)

    @patch("infraverse.sync.providers.build_providers_from_accounts")
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_syncs_active_account(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine = MagicMock()
        mock_engine.run.return_value = {
            "yandex_cloud": {"created": 2, "updated": 1, "errors": 0,
                             "vm_errors": {}, "synced_vms": {"vm1", "vm2"}},
        }
        mock_engine_cls.return_value = mock_engine

        svc = self._make_svc()
        account = self._make_account()

        result = svc._run_netbox_sync(accounts=[account])

        assert result["yandex_cloud"]["created"] == 2
        mock_engine_cls.assert_called_once()
        mock_engine.run.assert_called_once()
        mock_build.assert_called_once_with([account])

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_skips_inactive_account(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        svc = self._make_svc()
        account = self._make_account(is_active=False)

        result = svc._run_netbox_sync(accounts=[account])

        # build_providers_from_accounts filters inactive accounts
        mock_build.assert_called_once_with([account])
        assert result == {}

    @patch("infraverse.sync.providers.build_providers_from_accounts")
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_collects_vm_errors(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine = MagicMock()
        mock_engine.run.return_value = {
            "yandex_cloud": {
                "created": 0, "errors": 1,
                "vm_errors": {"broken-vm": "400 duplicate key"},
                "synced_vms": set(),
            },
        }
        mock_engine_cls.return_value = mock_engine

        svc = self._make_svc()
        result = svc._run_netbox_sync(accounts=[self._make_account()])

        assert result["yandex_cloud"]["vm_errors"] == {"broken-vm": "400 duplicate key"}

    @patch("infraverse.sync.providers.build_providers_from_accounts")
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_handles_engine_exception(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine_cls.side_effect = RuntimeError("API timeout")

        svc = self._make_svc()
        result = svc._run_netbox_sync(accounts=[self._make_account()])

        assert "API timeout" in result["error"]

    def test_returns_none_when_no_netbox_url(self):
        svc = self._make_svc(netbox_url=None, netbox_token="nb-token")
        result = svc._run_netbox_sync(accounts=[self._make_account()])
        assert result is None

    def test_returns_none_when_no_netbox_token(self):
        svc = self._make_svc(netbox_url="https://netbox.example.com", netbox_token=None)
        result = svc._run_netbox_sync(accounts=[self._make_account()])
        assert result is None

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_returns_empty_when_no_accounts(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        svc = self._make_svc()
        result = svc._run_netbox_sync(accounts=[])
        assert result == {}

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_returns_empty_when_accounts_is_none(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        svc = self._make_svc()
        result = svc._run_netbox_sync(accounts=None)
        assert result == {}

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_skips_unknown_provider_type(self, mock_engine_cls, mock_nb_cls, mock_build):
        """Unknown provider type is filtered out by build_providers_from_accounts."""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        svc = self._make_svc()
        account = self._make_account(provider_type="aws")

        result = svc._run_netbox_sync(accounts=[account])

        assert result == {}

    @patch("infraverse.sync.providers.build_providers_from_accounts")
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_multiple_accounts(self, mock_engine_cls, mock_nb_cls, mock_build):
        mock_engine = MagicMock()
        mock_engine.run.return_value = {
            "yandex_cloud": {"created": 3, "errors": 0, "vm_errors": {}, "synced_vms": {"vm1"}},
            "vcloud": {"created": 1, "errors": 0, "vm_errors": {}, "synced_vms": {"vm2"}},
        }
        mock_engine_cls.return_value = mock_engine

        svc = self._make_svc()
        acct1 = self._make_account(name="yc-acct")
        acct2 = self._make_account(name="vcd-acct", provider_type="vcloud",
                                   config={"url": "u", "username": "u", "password": "p"})

        result = svc._run_netbox_sync(accounts=[acct1, acct2])

        assert "yandex_cloud" in result
        assert "vcloud" in result
        mock_engine.run.assert_called_once()

    @patch("infraverse.sync.providers.build_providers_from_accounts")
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    def test_passes_dry_run_false_in_config_file_mode(self, mock_engine_cls, mock_nb_cls, mock_build):
        """Config-file mode always passes dry_run=False to SyncEngine."""
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        svc = self._make_svc()
        svc._run_netbox_sync(accounts=[self._make_account()])

        _, kwargs = mock_engine_cls.call_args
        assert kwargs.get("dry_run", False) is False

    @patch("infraverse.scheduler.run_ingestion_cycle")
    @patch("infraverse.sync.providers.build_providers_from_accounts")
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_ingestion_stores_vm_sync_errors_config_file_mode(
        self, mock_repo_cls, mock_ingestor_cls,
        mock_engine_cls, mock_nb_cls, mock_build, mock_cycle,
    ):
        """Full integration: _run_ingestion -> _run_netbox_sync -> _store_vm_sync_errors."""
        mock_cycle.return_value = {}

        account = MagicMock()
        account.id = 1
        account.is_active = True
        account.provider_type = "yandex_cloud"
        account.config = {"token": "t1"}
        account.name = "yc-acct"

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = [account]
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor_cls.return_value = mock_ingestor

        mock_engine = MagicMock()
        mock_engine.run.return_value = {
            "yandex_cloud": {
                "created": 0, "errors": 1,
                "vm_errors": {"broken-vm": "RequestError: 400"},
                "synced_vms": {"ok-vm"},
            },
        }
        mock_engine_cls.return_value = mock_engine

        nb = NetBoxConfig(url="https://netbox.example.com", token="nb-token")
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]}, netbox=nb)
        cfg = SimpleNamespace(netbox_url=None, netbox_token=None)
        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), cfg, infraverse_config=ic)
        svc._run_ingestion()

        # Verify update_vm_sync_errors was called with correct data
        mock_repo.update_vm_sync_errors.assert_called_once()
        call_args = mock_repo.update_vm_sync_errors.call_args[0]
        assert call_args[0] == {"broken-vm": "RequestError: 400"}
        assert call_args[1] == {"ok-vm"}


class TestSchedulerExclusionRules:
    """Tests for exclusion rules delegation to run_ingestion_cycle.

    Detailed exclusion rule handling tests are in tests/sync/test_orchestrator.py.
    These tests verify the scheduler passes infraverse_config (which contains
    exclusion rules) to run_ingestion_cycle correctly.
    """

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_infraverse_config_with_rules_passed_to_cycle(self, mock_cycle):
        mock_cycle.return_value = {}
        rules = [
            MonitoringExclusionRule(name_pattern="cl1*", reason="K8s workers"),
        ]
        ic = _make_infraverse_config(
            tenants={"t": [("a", "yandex_cloud")]},
            monitoring_exclusions=rules,
        )

        session = MagicMock()
        cfg = _make_config()
        svc = SchedulerService(_make_session_factory(session), cfg, infraverse_config=ic)
        svc._run_ingestion()

        mock_cycle.assert_called_once_with(session, infraverse_config=ic, legacy_config=cfg)

    @patch("infraverse.scheduler.run_ingestion_cycle")
    def test_no_infraverse_config_passes_none(self, mock_cycle):
        mock_cycle.return_value = {}

        cfg = _make_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        svc._run_ingestion()

        call_kwargs = mock_cycle.call_args.kwargs
        assert call_kwargs["infraverse_config"] is None
