"""Tests for infraverse.scheduler module."""

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from infraverse.config import Config
from infraverse.config_file import InfraverseConfig, MonitoringConfig, MonitoringExclusionRule, NetBoxConfig, TenantConfig, CloudAccountConfig
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

        mock_ingestor_cls.assert_called_once_with(session, exclusion_rules=[])
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

        cfg = _make_config(yc_token="test-token", yc_sa_key_file=None)
        svc = SchedulerService(_make_session_factory(), cfg)

        with patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            providers = svc._build_providers([account])

        assert providers == {1: mock_provider}
        call_kwargs = mock_yc_cls.call_args.kwargs
        assert call_kwargs["token_provider"].get_token() == "test-token"

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_builds_yandex_with_sa_key_file(self, mock_yc_cls, tmp_path):
        import json

        sa_key = {
            "id": "key-id",
            "service_account_id": "sa-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
        }
        key_file = tmp_path / "sa-key.json"
        key_file.write_text(json.dumps(sa_key))

        mock_provider = MagicMock()
        mock_yc_cls.return_value = mock_provider

        account = MagicMock()
        account.id = 1
        account.provider_type = "yandex_cloud"
        account.config = {}

        cfg = _make_config(yc_token="", yc_sa_key_file=str(key_file))
        svc = SchedulerService(_make_session_factory(), cfg)

        with patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            providers = svc._build_providers([account])

        assert providers == {1: mock_provider}
        call_kwargs = mock_yc_cls.call_args.kwargs
        from infraverse.providers.yc_auth import ServiceAccountKeyProvider
        assert isinstance(call_kwargs["token_provider"], ServiceAccountKeyProvider)

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

    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_run_ingestion_calls_config_sync(self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config(), infraverse_config=ic)
        svc._run_ingestion()

        mock_sync_cfg.assert_called_once_with(ic, session)

    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_run_ingestion_without_infraverse_config_skips_sync(self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._run_ingestion()

        mock_sync_cfg.assert_not_called()

    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_run_ingestion_filters_active_accounts(self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud", {"token": "t1"})]})

        active = MagicMock()
        active.id = 1
        active.is_active = True
        active.provider_type = "yandex_cloud"
        active.config = {"token": "t1"}
        active.name = "active-yc"

        inactive = MagicMock()
        inactive.id = 2
        inactive.is_active = False
        inactive.provider_type = "yandex_cloud"
        inactive.config = {"token": "old"}
        inactive.name = "inactive-yc"

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = [active, inactive]
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.yandex.YandexCloudClient") as mock_yc_cls, \
             patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            mock_yc_cls.return_value = MagicMock()
            svc._run_ingestion()

        providers = mock_ingestor.ingest_all.call_args[0][0]
        assert 1 in providers
        assert 2 not in providers


class TestBuildProvidersFromAccountConfig:
    """Tests for _build_providers reading credentials from account.config dict."""

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_builds_yandex_from_account_config(self, mock_yc_cls):
        mock_provider = MagicMock()
        mock_yc_cls.return_value = mock_provider

        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        account = MagicMock()
        account.id = 1
        account.provider_type = "yandex_cloud"
        account.config = {"token": "from-account-config"}
        account.name = "yc-acct"

        svc = SchedulerService(_make_session_factory(), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            providers = svc._build_providers([account])

        assert providers == {1: mock_provider}
        call_kwargs = mock_yc_cls.call_args.kwargs
        assert call_kwargs["token_provider"].get_token() == "from-account-config"

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_builds_yandex_from_sa_key_file_in_account(self, mock_yc_cls, tmp_path):
        import json

        sa_key = {
            "id": "key-id",
            "service_account_id": "sa-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
        }
        key_file = tmp_path / "sa-key.json"
        key_file.write_text(json.dumps(sa_key))

        mock_provider = MagicMock()
        mock_yc_cls.return_value = mock_provider

        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        account = MagicMock()
        account.id = 1
        account.provider_type = "yandex_cloud"
        account.config = {"sa_key_file": str(key_file)}
        account.name = "yc-sa"

        svc = SchedulerService(_make_session_factory(), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            providers = svc._build_providers([account])

        assert providers == {1: mock_provider}
        call_kwargs = mock_yc_cls.call_args.kwargs
        from infraverse.providers.yc_auth import ServiceAccountKeyProvider
        assert isinstance(call_kwargs["token_provider"], ServiceAccountKeyProvider)

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    def test_builds_vcloud_from_account_config(self, mock_vcd_cls):
        mock_provider = MagicMock()
        mock_vcd_cls.return_value = mock_provider

        ic = _make_infraverse_config(tenants={"t": [("a", "vcloud")]})
        account = MagicMock()
        account.id = 2
        account.provider_type = "vcloud"
        account.config = {
            "url": "https://vcd.example.com",
            "username": "admin",
            "password": "secret",
            "org": "MyOrg",
        }
        account.name = "vcd-acct"

        svc = SchedulerService(_make_session_factory(), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.yandex.YandexCloudClient"):
            providers = svc._build_providers([account])

        assert providers == {2: mock_provider}
        mock_vcd_cls.assert_called_once_with(
            url="https://vcd.example.com",
            username="admin",
            password="secret",
            org="MyOrg",
        )

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    def test_vcloud_from_account_config_defaults_org(self, mock_vcd_cls):
        ic = _make_infraverse_config(tenants={"t": [("a", "vcloud")]})
        account = MagicMock()
        account.id = 2
        account.provider_type = "vcloud"
        account.config = {
            "url": "https://vcd.example.com",
            "username": "admin",
            "password": "secret",
        }
        account.name = "vcd-acct"

        svc = SchedulerService(_make_session_factory(), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.yandex.YandexCloudClient"):
            svc._build_providers([account])

        call_kwargs = mock_vcd_cls.call_args.kwargs
        assert call_kwargs["org"] == "System"

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_skips_unknown_provider_with_config(self, mock_yc_cls, mock_vcd_cls):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        account = MagicMock()
        account.id = 3
        account.provider_type = "aws"
        account.config = {}
        account.name = "aws-acct"

        svc = SchedulerService(_make_session_factory(), _make_config(), infraverse_config=ic)
        providers = svc._build_providers([account])
        assert providers == {}

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_handles_provider_init_error_with_config(self, mock_yc_cls):
        mock_yc_cls.side_effect = RuntimeError("auth error")

        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        account = MagicMock()
        account.id = 1
        account.provider_type = "yandex_cloud"
        account.config = {"token": "bad"}
        account.name = "broken"

        svc = SchedulerService(_make_session_factory(), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            providers = svc._build_providers([account])
        assert providers == {}


class TestBuildZabbixClientWithMonitoringConfig:
    """Tests for _build_zabbix_client with monitoring config from InfraverseConfig."""

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_builds_from_infraverse_monitoring(self, mock_zabbix_cls):
        mock_client = MagicMock()
        mock_zabbix_cls.return_value = mock_client

        monitoring = MonitoringConfig(
            zabbix_url="https://zabbix.config.com/api",
            zabbix_username="config-user",
            zabbix_password="config-pass",
        )
        ic = _make_infraverse_config(
            tenants={"t": [("a", "yandex_cloud")]},
            monitoring=monitoring,
        )
        cfg = _make_config(zabbix_configured=False)
        svc = SchedulerService(_make_session_factory(), cfg, infraverse_config=ic)

        result = svc._build_zabbix_client()

        assert result is mock_client
        mock_zabbix_cls.assert_called_once_with(
            url="https://zabbix.config.com/api",
            username="config-user",
            password="config-pass",
        )

    def test_returns_none_when_infraverse_config_has_no_monitoring(self):
        """When using YAML config mode without monitoring section, returns None without falling back to env vars."""
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})  # no monitoring
        cfg = _make_config(
            zabbix_configured=True,
            zabbix_url="https://zabbix.env.com",
            zabbix_user="env-user",
            zabbix_password="env-pass",
        )
        svc = SchedulerService(_make_session_factory(), cfg, infraverse_config=ic)

        result = svc._build_zabbix_client()

        assert result is None

    def test_returns_none_when_neither_configured(self):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        cfg = _make_config(zabbix_configured=False)
        svc = SchedulerService(_make_session_factory(), cfg, infraverse_config=ic)
        assert svc._build_zabbix_client() is None

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_infraverse_monitoring_takes_precedence(self, mock_zabbix_cls):
        mock_client = MagicMock()
        mock_zabbix_cls.return_value = mock_client

        monitoring = MonitoringConfig(
            zabbix_url="https://zabbix.config.com/api",
            zabbix_username="config-user",
            zabbix_password="config-pass",
        )
        ic = _make_infraverse_config(
            tenants={"t": [("a", "yandex_cloud")]},
            monitoring=monitoring,
        )
        cfg = _make_config(
            zabbix_configured=True,
            zabbix_url="https://zabbix.env.com",
            zabbix_user="env-user",
            zabbix_password="env-pass",
        )
        svc = SchedulerService(_make_session_factory(), cfg, infraverse_config=ic)

        svc._build_zabbix_client()

        mock_zabbix_cls.assert_called_once_with(
            url="https://zabbix.config.com/api",
            username="config-user",
            password="config-pass",
        )


class TestSchedulerMultiTenant:
    """Tests for scheduler with multiple tenants and accounts."""

    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_multiple_tenants_multiple_providers(self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg):
        ic = _make_infraverse_config(tenants={
            "acme": [("acme-yc", "yandex_cloud", {"token": "t1"})],
            "beta": [("beta-yc", "yandex_cloud", {"token": "t2"})],
        })

        acme_acct = MagicMock()
        acme_acct.id = 1
        acme_acct.is_active = True
        acme_acct.provider_type = "yandex_cloud"
        acme_acct.config = {"token": "t1"}
        acme_acct.name = "acme-yc"

        beta_acct = MagicMock()
        beta_acct.id = 2
        beta_acct.is_active = True
        beta_acct.provider_type = "yandex_cloud"
        beta_acct.config = {"token": "t2"}
        beta_acct.name = "beta-yc"

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = [acme_acct, beta_acct]
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.yandex.YandexCloudClient") as mock_yc_cls, \
             patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            mock_yc_cls.side_effect = lambda token_provider=None, **kw: MagicMock()
            svc._run_ingestion()

        providers = mock_ingestor.ingest_all.call_args[0][0]
        assert len(providers) == 2
        assert 1 in providers
        assert 2 in providers

    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_mixed_provider_types(self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg):
        ic = _make_infraverse_config(tenants={
            "acme": [
                ("acme-yc", "yandex_cloud", {"token": "t1"}),
                ("acme-vcd", "vcloud", {"url": "https://vcd.example.com", "username": "admin", "password": "pass", "org": "Org1"}),
            ],
        })

        yc_acct = MagicMock()
        yc_acct.id = 1
        yc_acct.is_active = True
        yc_acct.provider_type = "yandex_cloud"
        yc_acct.config = {"token": "t1"}
        yc_acct.name = "acme-yc"

        vcd_acct = MagicMock()
        vcd_acct.id = 2
        vcd_acct.is_active = True
        vcd_acct.provider_type = "vcloud"
        vcd_acct.config = {"url": "https://vcd.example.com", "username": "admin", "password": "pass", "org": "Org1"}
        vcd_acct.name = "acme-vcd"

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = [yc_acct, vcd_acct]
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.yandex.YandexCloudClient") as mock_yc_cls, \
             patch("infraverse.providers.vcloud.VCloudDirectorClient") as mock_vcd_cls:
            mock_yc_cls.return_value = MagicMock()
            mock_vcd_cls.return_value = MagicMock()
            svc._run_ingestion()

        providers = mock_ingestor.ingest_all.call_args[0][0]
        assert len(providers) == 2
        assert 1 in providers
        assert 2 in providers

    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_active_and_inactive_mixed(self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg):
        ic = _make_infraverse_config(tenants={
            "acme": [("acme-yc", "yandex_cloud", {"token": "t1"})],
        })

        active = MagicMock()
        active.id = 1
        active.is_active = True
        active.provider_type = "yandex_cloud"
        active.config = {"token": "t1"}
        active.name = "acme-yc"

        inactive1 = MagicMock()
        inactive1.id = 2
        inactive1.is_active = False
        inactive1.provider_type = "yandex_cloud"
        inactive1.config = {"token": "old1"}
        inactive1.name = "old-yc"

        inactive2 = MagicMock()
        inactive2.id = 3
        inactive2.is_active = False
        inactive2.provider_type = "vcloud"
        inactive2.config = {"url": "https://old.vcd.com"}
        inactive2.name = "old-vcd"

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = [active, inactive1, inactive2]
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config(), infraverse_config=ic)

        with patch("infraverse.providers.yandex.YandexCloudClient") as mock_yc_cls, \
             patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            mock_yc_cls.return_value = MagicMock()
            svc._run_ingestion()

        providers = mock_ingestor.ingest_all.call_args[0][0]
        assert len(providers) == 1
        assert 1 in providers


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

    def test_skipped_when_config_is_simple_namespace(self):
        cfg = SimpleNamespace(yc_token="t", netbox_url="u", netbox_token="n")
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

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_ingestion_result_includes_netbox_sync(self, mock_repo_cls, mock_ingestor_cls, mock_engine_cls, mock_nb_cls, mock_build):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {"yc": "ok"}
        mock_ingestor_cls.return_value = mock_ingestor

        mock_engine = MagicMock()
        mock_engine.run.return_value = {"vms_synced": 3}
        mock_engine_cls.return_value = mock_engine

        cfg = _make_real_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        svc._run_ingestion()

        assert svc._last_result["yc"] == "ok"
        assert svc._last_result["netbox_sync"] == {"vms_synced": 3}
        assert svc._last_result["netbox_ingestion"] == "success"

    @patch("infraverse.sync.providers.build_providers_from_accounts", return_value=[])
    @patch("infraverse.providers.netbox.NetBoxClient")
    @patch("infraverse.sync.engine.SyncEngine")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_netbox_failure_does_not_affect_ingestion_result(self, mock_repo_cls, mock_ingestor_cls, mock_engine_cls, mock_nb_cls, mock_build):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {"yc": "ok"}
        mock_ingestor_cls.return_value = mock_ingestor

        mock_engine_cls.side_effect = RuntimeError("netbox down")

        cfg = _make_real_config()
        svc = SchedulerService(_make_session_factory(), cfg)
        svc._run_ingestion()

        assert svc._last_result["yc"] == "ok"
        assert svc._last_result["netbox_sync"] == {"error": "netbox down"}

    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_no_netbox_sync_key_when_config_is_mock(self, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {"yc": "ok"}
        mock_ingestor_cls.return_value = mock_ingestor

        cfg = _make_config()  # MagicMock
        svc = SchedulerService(_make_session_factory(), cfg)
        svc._run_ingestion()

        assert svc._last_result == {"yc": "ok"}
        assert "netbox_sync" not in svc._last_result


class TestRunNetboxSyncConfigFileMode:
    """Tests for _run_netbox_sync in config-file mode (per-account sync)."""

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

    @patch("infraverse.sync.batch.sync_vms_optimized")
    @patch("infraverse.sync.infrastructure.sync_infrastructure")
    @patch("infraverse.providers.netbox.NetBoxClient")
    def test_syncs_active_account(self, mock_nb_cls, mock_sync_infra, mock_sync_vms):
        mock_nb = MagicMock()
        mock_nb_cls.return_value = mock_nb
        mock_sync_infra.return_value = {"zones": {}, "folders": {}}
        mock_sync_vms.return_value = {
            "created": 2, "updated": 1, "errors": 0,
            "vm_errors": {}, "synced_vms": {"vm1", "vm2"},
        }

        svc = self._make_svc()
        account = self._make_account()

        with patch.object(svc, "_build_provider_from_account") as mock_build:
            mock_client = MagicMock()
            mock_client.fetch_all_data.return_value = {"vms": [{"name": "vm1"}, {"name": "vm2"}]}
            mock_build.return_value = mock_client

            result = svc._run_netbox_sync(accounts=[account])

        assert "acme-yc" in result
        assert result["acme-yc"]["created"] == 2
        mock_sync_infra.assert_called_once()
        mock_sync_vms.assert_called_once()

    @patch("infraverse.sync.batch.sync_vms_optimized")
    @patch("infraverse.sync.infrastructure.sync_infrastructure")
    @patch("infraverse.providers.netbox.NetBoxClient")
    def test_skips_inactive_account(self, mock_nb_cls, mock_sync_infra, mock_sync_vms):
        mock_nb_cls.return_value = MagicMock()
        svc = self._make_svc()
        account = self._make_account(is_active=False)

        result = svc._run_netbox_sync(accounts=[account])

        assert result == {}
        mock_sync_infra.assert_not_called()
        mock_sync_vms.assert_not_called()

    @patch("infraverse.sync.batch.sync_vms_optimized")
    @patch("infraverse.sync.infrastructure.sync_infrastructure")
    @patch("infraverse.providers.netbox.NetBoxClient")
    def test_collects_vm_errors(self, mock_nb_cls, mock_sync_infra, mock_sync_vms):
        mock_nb_cls.return_value = MagicMock()
        mock_sync_infra.return_value = {"zones": {}, "folders": {}}
        mock_sync_vms.return_value = {
            "created": 0, "errors": 1,
            "vm_errors": {"broken-vm": "400 duplicate key"},
            "synced_vms": set(),
        }

        svc = self._make_svc()
        account = self._make_account()

        with patch.object(svc, "_build_provider_from_account") as mock_build:
            mock_client = MagicMock()
            mock_client.fetch_all_data.return_value = {"vms": [{"name": "broken-vm"}]}
            mock_build.return_value = mock_client

            result = svc._run_netbox_sync(accounts=[account])

        assert result["acme-yc"]["vm_errors"] == {"broken-vm": "400 duplicate key"}

    @patch("infraverse.providers.netbox.NetBoxClient")
    def test_handles_fetch_data_failure(self, mock_nb_cls):
        mock_nb_cls.return_value = MagicMock()
        svc = self._make_svc()
        account = self._make_account()

        with patch.object(svc, "_build_provider_from_account") as mock_build:
            mock_client = MagicMock()
            mock_client.fetch_all_data.return_value = None
            mock_build.return_value = mock_client

            result = svc._run_netbox_sync(accounts=[account])

        assert result["acme-yc"]["error"] == "failed to fetch cloud data"

    @patch("infraverse.providers.netbox.NetBoxClient")
    def test_handles_provider_exception(self, mock_nb_cls):
        mock_nb_cls.return_value = MagicMock()
        svc = self._make_svc()
        account = self._make_account()

        with patch.object(svc, "_build_provider_from_account") as mock_build:
            mock_client = MagicMock()
            mock_client.fetch_all_data.side_effect = RuntimeError("API timeout")
            mock_build.return_value = mock_client

            result = svc._run_netbox_sync(accounts=[account])

        assert "API timeout" in result["acme-yc"]["error"]

    def test_returns_none_when_no_netbox_url(self):
        svc = self._make_svc(netbox_url=None, netbox_token="nb-token")
        result = svc._run_netbox_sync(accounts=[self._make_account()])
        assert result is None

    def test_returns_none_when_no_netbox_token(self):
        svc = self._make_svc(netbox_url="https://netbox.example.com", netbox_token=None)
        result = svc._run_netbox_sync(accounts=[self._make_account()])
        assert result is None

    def test_returns_none_when_no_accounts(self):
        svc = self._make_svc()
        result = svc._run_netbox_sync(accounts=[])
        assert result is None

    def test_returns_none_when_accounts_is_none(self):
        svc = self._make_svc()
        result = svc._run_netbox_sync(accounts=None)
        assert result is None

    @patch("infraverse.providers.netbox.NetBoxClient")
    def test_skips_unknown_provider_type(self, mock_nb_cls):
        mock_nb_cls.return_value = MagicMock()
        svc = self._make_svc()
        account = self._make_account(provider_type="aws")

        result = svc._run_netbox_sync(accounts=[account])

        assert result == {}

    @patch("infraverse.sync.batch.sync_vms_optimized")
    @patch("infraverse.sync.infrastructure.sync_infrastructure")
    @patch("infraverse.providers.netbox.NetBoxClient")
    def test_multiple_accounts(self, mock_nb_cls, mock_sync_infra, mock_sync_vms):
        mock_nb_cls.return_value = MagicMock()
        mock_sync_infra.return_value = {"zones": {}, "folders": {}}
        mock_sync_vms.side_effect = [
            {"created": 3, "errors": 0, "vm_errors": {}, "synced_vms": {"vm1"}},
            {"created": 1, "errors": 0, "vm_errors": {}, "synced_vms": {"vm2"}},
        ]

        svc = self._make_svc()
        acct1 = self._make_account(name="yc-acct")
        acct2 = self._make_account(name="vcd-acct", provider_type="vcloud", config={"url": "u", "username": "u", "password": "p"})

        with patch.object(svc, "_build_provider_from_account") as mock_build:
            mock_client = MagicMock()
            mock_client.fetch_all_data.return_value = {"vms": [{"name": "vm1"}]}
            mock_build.return_value = mock_client

            result = svc._run_netbox_sync(accounts=[acct1, acct2])

        assert "yc-acct" in result
        assert "vcd-acct" in result
        assert mock_sync_vms.call_count == 2

    @patch("infraverse.sync.batch.sync_vms_optimized")
    @patch("infraverse.sync.infrastructure.sync_infrastructure")
    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_ingestion_stores_vm_sync_errors_config_file_mode(
        self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg,
        mock_sync_infra, mock_sync_vms,
    ):
        """Full integration: _run_ingestion → _run_netbox_sync → _store_vm_sync_errors."""
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
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        mock_sync_infra.return_value = {"zones": {}, "folders": {}}
        mock_sync_vms.return_value = {
            "created": 0, "errors": 1,
            "vm_errors": {"broken-vm": "RequestError: 400"},
            "synced_vms": {"ok-vm"},
        }

        nb = NetBoxConfig(url="https://netbox.example.com", token="nb-token")
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]}, netbox=nb)
        cfg = SimpleNamespace(netbox_url=None, netbox_token=None)
        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), cfg, infraverse_config=ic)

        with patch.object(svc, "_build_provider_from_account") as mock_build, \
             patch("infraverse.providers.netbox.NetBoxClient"):
            mock_client = MagicMock()
            mock_client.fetch_all_data.return_value = {"vms": [{"name": "broken-vm"}, {"name": "ok-vm"}]}
            mock_build.return_value = mock_client

            svc._run_ingestion()

        # Verify update_vm_sync_errors was called with correct data
        mock_repo.update_vm_sync_errors.assert_called_once()
        call_args = mock_repo.update_vm_sync_errors.call_args[0]
        assert call_args[0] == {"broken-vm": "RequestError: 400"}
        assert call_args[1] == {"ok-vm"}


class TestSchedulerExclusionRules:
    """Tests for exclusion rules being passed from config to DataIngestor."""

    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_exclusion_rules_passed_to_ingestor(self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg):
        rules = [
            MonitoringExclusionRule(name_pattern="cl1*", reason="K8s workers"),
        ]
        ic = _make_infraverse_config(
            tenants={"t": [("a", "yandex_cloud")]},
            monitoring_exclusions=rules,
        )
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config(), infraverse_config=ic)
        svc._run_ingestion()

        mock_ingestor_cls.assert_called_once_with(session, exclusion_rules=rules)

    @patch("infraverse.scheduler.sync_config_to_db")
    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_no_exclusion_rules_passes_empty_list(self, mock_repo_cls, mock_ingestor_cls, mock_sync_cfg):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        svc = SchedulerService(_make_session_factory(session), _make_config(), infraverse_config=ic)
        svc._run_ingestion()

        mock_ingestor_cls.assert_called_once_with(session, exclusion_rules=[])

    @patch("infraverse.scheduler.DataIngestor")
    @patch("infraverse.scheduler.Repository")
    def test_no_infraverse_config_passes_empty_rules(self, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        svc = SchedulerService(_make_session_factory(), _make_config())
        svc._run_ingestion()

        # Without infraverse_config, empty exclusion rules are passed
        call_kwargs = mock_ingestor_cls.call_args[1]
        assert call_kwargs["exclusion_rules"] == []
