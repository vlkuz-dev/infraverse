"""Tests for infraverse.sync.orchestrator module."""

from unittest.mock import MagicMock, patch

from infraverse.config_file import (
    CloudAccountConfig,
    InfraverseConfig,
    MonitoringConfig,
    MonitoringExclusionRule,
    TenantConfig,
)
from infraverse.sync.orchestrator import (
    _build_legacy_provider,
    _build_providers_for_ingestion,
    run_ingestion_cycle,
)


def _make_infraverse_config(tenants=None, monitoring=None, monitoring_exclusions=None):
    """Create an InfraverseConfig for testing."""
    t = {}
    for tname, accounts in (tenants or {}).items():
        accs = [
            CloudAccountConfig(
                name=a[0], provider=a[1],
                credentials=a[2] if len(a) > 2 else {},
            )
            for a in accounts
        ]
        t[tname] = TenantConfig(name=tname, cloud_accounts=accs)
    return InfraverseConfig(
        tenants=t, monitoring=monitoring,
        monitoring_exclusions=monitoring_exclusions or [],
    )


def _make_account(account_id, provider_type, name="test", is_active=True, config=None):
    """Create a mock CloudAccount."""
    account = MagicMock()
    account.id = account_id
    account.provider_type = provider_type
    account.name = name
    account.is_active = is_active
    account.config = config or {}
    return account


def _make_legacy_config(**overrides):
    """Create a mock legacy Config."""
    config = MagicMock()
    config.yc_token = "test-token"
    config.yc_sa_key_file = None
    config.vcd_configured = False
    config.zabbix_configured = False
    for k, v in overrides.items():
        setattr(config, k, v)
    return config


class TestRunIngestionCycleWithInfraverseConfig:
    """Tests for run_ingestion_cycle in config-file mode."""

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.sync_config_to_db")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_calls_config_sync(self, mock_zabbix, mock_sync_cfg, mock_repo_cls, mock_ingestor_cls):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        run_ingestion_cycle(session, infraverse_config=ic)

        mock_sync_cfg.assert_called_once_with(ic, session)
        session.commit.assert_called_once()

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.sync_config_to_db")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_filters_active_accounts(self, mock_zabbix, mock_sync_cfg, mock_repo_cls, mock_ingestor_cls):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud", {"token": "t1"})]})

        active = _make_account(1, "yandex_cloud", "active-yc", is_active=True, config={"token": "t1"})
        inactive = _make_account(2, "yandex_cloud", "inactive-yc", is_active=False, config={"token": "old"})

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = [active, inactive]
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        with patch("infraverse.providers.yandex.YandexCloudClient"):
            run_ingestion_cycle(session, infraverse_config=ic)

        providers = mock_ingestor.ingest_all.call_args[0][0]
        assert 1 in providers
        assert 2 not in providers

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.sync_config_to_db")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_passes_exclusion_rules(self, mock_zabbix, mock_sync_cfg, mock_repo_cls, mock_ingestor_cls):
        rule = MonitoringExclusionRule(name_pattern="test-*", reason="test exclusion")
        ic = _make_infraverse_config(
            tenants={"t": [("a", "yandex_cloud")]},
            monitoring_exclusions=[rule],
        )
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        run_ingestion_cycle(session, infraverse_config=ic)

        mock_ingestor_cls.assert_called_once_with(session, exclusion_rules=[rule])

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.sync_config_to_db")
    @patch("infraverse.sync.orchestrator.build_zabbix_client")
    def test_passes_zabbix_client(self, mock_build_zabbix, mock_sync_cfg, mock_repo_cls, mock_ingestor_cls):
        mock_zabbix = MagicMock()
        mock_build_zabbix.return_value = mock_zabbix

        ic = _make_infraverse_config(
            tenants={"t": [("a", "yandex_cloud")]},
            monitoring=MonitoringConfig(
                zabbix_url="https://zabbix.test",
                zabbix_username="admin",
                zabbix_password="pass",
            ),
        )
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        run_ingestion_cycle(session, infraverse_config=ic)

        mock_build_zabbix.assert_called_once_with(
            infraverse_config=ic, legacy_config=None,
        )
        zabbix_arg = mock_ingestor.ingest_all.call_args[0][1]
        assert zabbix_arg is mock_zabbix

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.sync_config_to_db")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_returns_ingest_results(self, mock_zabbix, mock_sync_cfg, mock_repo_cls, mock_ingestor_cls):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {"yc": "success"}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        results = run_ingestion_cycle(session, infraverse_config=ic)

        assert results == {"yc": "success"}


class TestRunIngestionCycleWithLegacyConfig:
    """Tests for run_ingestion_cycle in env-var mode."""

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.sync_config_to_db")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_skips_config_sync(self, mock_zabbix, mock_sync_cfg, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        legacy = _make_legacy_config()
        run_ingestion_cycle(session, legacy_config=legacy)

        mock_sync_cfg.assert_not_called()
        session.commit.assert_not_called()

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_does_not_filter_accounts(self, mock_zabbix, mock_repo_cls, mock_ingestor_cls):
        """Without infraverse_config, all accounts are used (no active filter)."""
        active = _make_account(1, "yandex_cloud", "yc1", is_active=True, config={"token": "t1"})
        inactive = _make_account(2, "yandex_cloud", "yc2", is_active=False, config={"token": "t2"})

        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = [active, inactive]
        mock_repo_cls.return_value = mock_repo

        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        legacy = _make_legacy_config()

        with patch("infraverse.providers.yandex.YandexCloudClient"):
            run_ingestion_cycle(session, legacy_config=legacy)

        providers = mock_ingestor.ingest_all.call_args[0][0]
        assert 1 in providers
        assert 2 in providers

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_no_exclusion_rules(self, mock_zabbix, mock_repo_cls, mock_ingestor_cls):
        """Without infraverse_config, exclusion_rules defaults to empty list."""
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        legacy = _make_legacy_config()
        run_ingestion_cycle(session, legacy_config=legacy)

        mock_ingestor_cls.assert_called_once_with(session, exclusion_rules=[])

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_returns_results(self, mock_zabbix, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {"test": "ok"}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        legacy = _make_legacy_config()
        result = run_ingestion_cycle(session, legacy_config=legacy)

        assert result == {"test": "ok"}


class TestRunIngestionCycleEmptyAccounts:
    """Tests for run_ingestion_cycle with no accounts."""

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.sync_config_to_db")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_empty_accounts_with_config(self, mock_zabbix, mock_sync_cfg, mock_repo_cls, mock_ingestor_cls):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        result = run_ingestion_cycle(session, infraverse_config=ic)

        assert result == {}
        mock_ingestor.ingest_all.assert_called_once_with({}, None)

    @patch("infraverse.sync.orchestrator.DataIngestor")
    @patch("infraverse.sync.orchestrator.Repository")
    @patch("infraverse.sync.orchestrator.build_zabbix_client", return_value=None)
    def test_empty_accounts_with_legacy(self, mock_zabbix, mock_repo_cls, mock_ingestor_cls):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all.return_value = {}
        mock_ingestor_cls.return_value = mock_ingestor

        session = MagicMock()
        result = run_ingestion_cycle(session, legacy_config=_make_legacy_config())

        assert result == {}
        mock_ingestor.ingest_all.assert_called_once_with({}, None)


class TestBuildProvidersForIngestion:
    """Tests for _build_providers_for_ingestion helper."""

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_config_file_mode(self, mock_yc_cls):
        mock_client = MagicMock()
        mock_yc_cls.return_value = mock_client
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        account = _make_account(1, "yandex_cloud", config={"token": "t1"})

        providers = _build_providers_for_ingestion([account], infraverse_config=ic)

        assert providers == {1: mock_client}

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_legacy_mode(self, mock_yc_cls):
        mock_client = MagicMock()
        mock_yc_cls.return_value = mock_client
        legacy = _make_legacy_config()
        account = _make_account(1, "yandex_cloud")

        providers = _build_providers_for_ingestion([account], legacy_config=legacy)

        assert providers == {1: mock_client}

    def test_skips_on_build_error(self):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        account = _make_account(1, "yandex_cloud", config={"token": "t1"})

        with patch("infraverse.sync.orchestrator.build_provider", side_effect=RuntimeError("fail")):
            providers = _build_providers_for_ingestion([account], infraverse_config=ic)

        assert providers == {}

    def test_unknown_provider_returns_empty(self):
        ic = _make_infraverse_config(tenants={"t": [("a", "yandex_cloud")]})
        account = _make_account(1, "aws", config={})

        providers = _build_providers_for_ingestion([account], infraverse_config=ic)

        assert providers == {}

    def test_no_config_returns_empty(self):
        """With neither infraverse_config nor legacy_config, no providers are built."""
        account = _make_account(1, "yandex_cloud")
        providers = _build_providers_for_ingestion([account])
        assert providers == {}


class TestBuildLegacyProvider:
    """Tests for _build_legacy_provider helper."""

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_builds_yandex_from_token(self, mock_yc_cls):
        mock_client = MagicMock()
        mock_yc_cls.return_value = mock_client
        account = _make_account(1, "yandex_cloud")
        config = _make_legacy_config(yc_token="my-token")

        result = _build_legacy_provider(account, config)

        assert result is mock_client

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_builds_yandex_from_sa_key_file(self, mock_yc_cls, tmp_path):
        import json

        sa_key = {
            "id": "key-id",
            "service_account_id": "sa-id",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
        }
        key_file = tmp_path / "sa-key.json"
        key_file.write_text(json.dumps(sa_key))

        mock_client = MagicMock()
        mock_yc_cls.return_value = mock_client
        account = _make_account(1, "yandex_cloud")
        config = _make_legacy_config(yc_sa_key_file=str(key_file))

        result = _build_legacy_provider(account, config)

        assert result is mock_client

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    def test_builds_vcloud(self, mock_vcd_cls):
        mock_client = MagicMock()
        mock_vcd_cls.return_value = mock_client
        account = _make_account(2, "vcloud", config={"org": "TestOrg"})
        config = _make_legacy_config(
            vcd_configured=True,
            vcd_url="https://vcd.example.com",
            vcd_user="admin",
            vcd_password="secret",
            vcd_org="DefaultOrg",
        )

        result = _build_legacy_provider(account, config)

        assert result is mock_client
        mock_vcd_cls.assert_called_once_with(
            url="https://vcd.example.com",
            username="admin",
            password="secret",
            org="TestOrg",
        )

    def test_vcloud_not_configured_returns_none(self):
        account = _make_account(2, "vcloud")
        config = _make_legacy_config(vcd_configured=False)

        result = _build_legacy_provider(account, config)

        assert result is None

    def test_unknown_provider_returns_none(self):
        account = _make_account(3, "aws")
        config = _make_legacy_config()

        result = _build_legacy_provider(account, config)

        assert result is None
