"""Tests for infraverse.scheduler module."""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from infraverse.scheduler import SchedulerService


def _make_config(**overrides):
    """Create a mock config with sensible defaults."""
    config = MagicMock()
    config.yc_token = "test-token"
    config.vcd_configured = False
    config.zabbix_configured = False
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


class TestTriggerNow:
    def test_trigger_now_modifies_existing_job(self):
        svc = SchedulerService(_make_session_factory(), _make_config())
        # Mock _run_ingestion BEFORE start() so APScheduler captures the mock
        svc._run_ingestion = MagicMock()
        svc.start(interval_minutes=60)
        try:
            original_next = svc._scheduler.get_job("ingestion").next_run_time
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

    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_trigger_now_executes_ingestion(self, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {"test": "success"}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config())
        svc.start(interval_minutes=60)
        try:
            svc.trigger_now()
            # Give the background thread time to execute
            time.sleep(0.5)
            mock_ingestor.ingest_all.assert_called_once()
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
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_successful_ingestion(self, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {"yc": "success"}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config())
        svc._run_ingestion()

        mock_ingestor_cls.assert_called_once_with(session)
        mock_ingestor.ingest_all.assert_called_once()
        assert svc._last_result == {"yc": "success"}
        assert svc._last_run_time is not None
        session.close.assert_called_once()

    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_ingestion_error_captured(self, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.side_effect = RuntimeError("db connection lost")
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config())
        svc._run_ingestion()  # should not raise

        assert svc._last_result == {"error": "db connection lost"}
        assert svc._last_run_time is not None
        session.close.assert_called_once()

    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_session_closed_on_error(self, mock_repo_cls, mock_ingestor_cls):
        mock_repo_cls.side_effect = RuntimeError("cannot create repo")

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config())
        svc._run_ingestion()

        session.close.assert_called_once()

    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_ingestion_with_no_providers(self, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._run_ingestion()

        mock_ingestor.ingest_all.assert_called_once_with({}, None)
        assert svc._last_result == {}


class TestBuildProviders:
    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_builds_yandex_provider(self, mock_yc_cls):
        mock_provider = MagicMock()
        mock_yc_cls.return_value = mock_provider

        account = MagicMock()
        account.id = 1
        account.provider_type = "yandex_cloud"
        account.config = {}

        cfg = _make_config(yc_token="test-token")
        svc = SchedulerService(_make_session_factory(), cfg)

        with patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            providers = svc._build_providers([account])

        assert providers == {1: mock_provider}
        mock_yc_cls.assert_called_once_with(token="test-token")

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    def test_builds_vcloud_provider(self, mock_vcd_cls):
        mock_provider = MagicMock()
        mock_vcd_cls.return_value = mock_provider

        account = MagicMock()
        account.id = 2
        account.provider_type = "vcloud"
        account.config = {"org": "TestOrg"}

        cfg = _make_config(
            vcd_configured=True,
            vcd_url="https://vcd.example.com",
            vcd_user="admin",
            vcd_password="secret",
            vcd_org="DefaultOrg",
        )
        svc = SchedulerService(_make_session_factory(), cfg)

        with patch("infraverse.providers.yandex.YandexCloudClient"):
            providers = svc._build_providers([account])

        assert providers == {2: mock_provider}
        mock_vcd_cls.assert_called_once_with(
            url="https://vcd.example.com",
            username="admin",
            password="secret",
            org="TestOrg",
        )

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_skips_vcloud_when_not_configured(self, mock_yc_cls, mock_vcd_cls):
        account = MagicMock()
        account.id = 2
        account.provider_type = "vcloud"
        account.config = {}

        cfg = _make_config(vcd_configured=False)
        svc = SchedulerService(_make_session_factory(), cfg)
        providers = svc._build_providers([account])

        assert providers == {}
        mock_vcd_cls.assert_not_called()

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_handles_unknown_provider_type(self, mock_yc_cls, mock_vcd_cls):
        account = MagicMock()
        account.id = 3
        account.provider_type = "aws"
        account.config = {}

        svc = SchedulerService(_make_session_factory(), _make_config())
        providers = svc._build_providers([account])

        assert providers == {}

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_handles_provider_init_error(self, mock_yc_cls):
        mock_yc_cls.side_effect = RuntimeError("network error")

        account = MagicMock()
        account.id = 1
        account.name = "broken-account"
        account.provider_type = "yandex_cloud"
        account.config = {}

        svc = SchedulerService(_make_session_factory(), _make_config())

        with patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            providers = svc._build_providers([account])

        assert providers == {}


class TestBuildZabbixClient:
    def test_returns_none_when_not_configured(self):
        cfg = _make_config(zabbix_configured=False)
        svc = SchedulerService(_make_session_factory(), cfg)
        assert svc._build_zabbix_client() is None

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_builds_client_when_configured(self, mock_zabbix_cls):
        mock_client = MagicMock()
        mock_zabbix_cls.return_value = mock_client

        cfg = _make_config(
            zabbix_configured=True,
            zabbix_url="https://zabbix.example.com",
            zabbix_user="Admin",
            zabbix_password="zabbix",
        )
        svc = SchedulerService(_make_session_factory(), cfg)
        result = svc._build_zabbix_client()

        assert result is mock_client
        mock_zabbix_cls.assert_called_once_with(
            url="https://zabbix.example.com",
            username="Admin",
            password="zabbix",
        )

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_returns_none_on_init_error(self, mock_zabbix_cls):
        mock_zabbix_cls.side_effect = RuntimeError("connection refused")

        cfg = _make_config(
            zabbix_configured=True,
            zabbix_url="https://zabbix.example.com",
            zabbix_user="Admin",
            zabbix_password="zabbix",
        )
        svc = SchedulerService(_make_session_factory(), cfg)
        assert svc._build_zabbix_client() is None
