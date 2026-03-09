"""Tests for infraverse.sync.providers module."""

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from infraverse.sync.providers import build_provider, build_providers_from_accounts, build_zabbix_client
from infraverse.sync.provider_profile import YC_PROFILE, VCLOUD_PROFILE


def _make_account(provider_type, config=None, name="test-account", is_active=True):
    return SimpleNamespace(
        provider_type=provider_type,
        config=config or {},
        name=name,
        is_active=is_active,
    )


class TestBuildProvider:
    @patch("infraverse.providers.yc_auth.resolve_token_provider")
    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_yandex_cloud_with_token(self, mock_yc_cls, mock_resolve):
        account = _make_account("yandex_cloud", {"token": "my-token"})
        mock_resolve.return_value = "fake-provider"

        client, profile = build_provider(account)

        mock_resolve.assert_called_once_with({"token": "my-token"})
        mock_yc_cls.assert_called_once_with(token_provider="fake-provider")
        assert profile is YC_PROFILE

    @patch("infraverse.providers.yc_auth.resolve_token_provider")
    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_yandex_cloud_with_sa_key_file(self, mock_yc_cls, mock_resolve):
        account = _make_account("yandex_cloud", {"sa_key_file": "/path/to/key.json"})
        mock_resolve.return_value = "sa-provider"

        client, profile = build_provider(account)

        mock_resolve.assert_called_once_with({"sa_key_file": "/path/to/key.json"})
        assert profile is YC_PROFILE

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    def test_vcloud(self, mock_vcd_cls):
        creds = {"url": "https://vcd.test", "username": "admin", "password": "pass", "org": "MyOrg"}
        account = _make_account("vcloud", creds)

        client, profile = build_provider(account)

        mock_vcd_cls.assert_called_once_with(
            url="https://vcd.test",
            username="admin",
            password="pass",
            org="MyOrg",
        )
        assert profile is VCLOUD_PROFILE

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    def test_vcloud_defaults_org(self, mock_vcd_cls):
        creds = {"url": "https://vcd.test", "username": "u", "password": "p"}
        account = _make_account("vcloud", creds)

        build_provider(account)

        assert mock_vcd_cls.call_args.kwargs["org"] == "System"

    def test_unknown_provider_returns_none(self):
        account = _make_account("aws")
        assert build_provider(account) is None

    def test_unknown_provider_logs_warning(self, caplog):
        import logging
        account = _make_account("aws")
        with caplog.at_level(logging.WARNING, logger="infraverse.sync.providers"):
            build_provider(account)
        assert "Unknown provider type 'aws'" in caplog.text

    @patch("infraverse.providers.yc_auth.resolve_token_provider")
    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_empty_config_still_works(self, mock_yc_cls, mock_resolve):
        account = _make_account("yandex_cloud", None)  # config=None

        build_provider(account)

        mock_resolve.assert_called_once_with({})


def _make_account_with_tenant(provider_type, tenant_name=None, config=None,
                              name="test-account", is_active=True):
    tenant = SimpleNamespace(name=tenant_name) if tenant_name else None
    return SimpleNamespace(
        provider_type=provider_type,
        config=config or {},
        name=name,
        is_active=is_active,
        tenant=tenant,
    )


class TestBuildProvidersFromAccounts:
    @patch("infraverse.sync.providers.build_provider")
    def test_builds_active_accounts(self, mock_build):
        mock_build.return_value = (MagicMock(), YC_PROFILE)
        accounts = [
            _make_account("yandex_cloud", name="acc-1"),
            _make_account("yandex_cloud", name="acc-2"),
        ]

        result = build_providers_from_accounts(accounts)

        assert len(result) == 2
        assert mock_build.call_count == 2

    @patch("infraverse.sync.providers.build_provider")
    def test_returns_3_tuples(self, mock_build):
        """Each result element is a 3-tuple: (client, profile, tenant_name)."""
        mock_build.return_value = (MagicMock(), YC_PROFILE)
        accounts = [_make_account("yandex_cloud")]

        result = build_providers_from_accounts(accounts)

        assert len(result) == 1
        assert len(result[0]) == 3
        client, profile, tenant_name = result[0]
        assert profile is YC_PROFILE
        assert tenant_name is None  # no tenant attr on simple account

    @patch("infraverse.sync.providers.build_provider")
    def test_extracts_tenant_name_from_account(self, mock_build):
        """tenant_name is extracted from account.tenant.name when available."""
        mock_build.return_value = (MagicMock(), YC_PROFILE)
        accounts = [_make_account_with_tenant("yandex_cloud", tenant_name="acme-corp")]

        result = build_providers_from_accounts(accounts)

        assert len(result) == 1
        _, _, tenant_name = result[0]
        assert tenant_name == "acme-corp"

    @patch("infraverse.sync.providers.build_provider")
    def test_tenant_name_none_when_no_tenant(self, mock_build):
        """tenant_name is None when account.tenant is None."""
        mock_build.return_value = (MagicMock(), YC_PROFILE)
        accounts = [_make_account_with_tenant("yandex_cloud", tenant_name=None)]

        result = build_providers_from_accounts(accounts)

        _, _, tenant_name = result[0]
        assert tenant_name is None

    @patch("infraverse.sync.providers.build_provider")
    def test_tenant_name_none_when_no_tenant_attr(self, mock_build):
        """tenant_name is None when account has no tenant attribute."""
        mock_build.return_value = (MagicMock(), YC_PROFILE)
        accounts = [_make_account("yandex_cloud")]  # no .tenant attr

        result = build_providers_from_accounts(accounts)

        _, _, tenant_name = result[0]
        assert tenant_name is None

    @patch("infraverse.sync.providers.build_provider")
    def test_multiple_accounts_different_tenants(self, mock_build):
        """Each account carries its own tenant_name."""
        mock_build.return_value = (MagicMock(), YC_PROFILE)
        accounts = [
            _make_account_with_tenant("yandex_cloud", tenant_name="acme-corp", name="acc-1"),
            _make_account_with_tenant("yandex_cloud", tenant_name="beta-inc", name="acc-2"),
        ]

        result = build_providers_from_accounts(accounts)

        assert len(result) == 2
        assert result[0][2] == "acme-corp"
        assert result[1][2] == "beta-inc"

    @patch("infraverse.sync.providers.build_provider")
    def test_skips_inactive_accounts(self, mock_build):
        mock_build.return_value = (MagicMock(), YC_PROFILE)
        accounts = [
            _make_account("yandex_cloud", name="active", is_active=True),
            _make_account("yandex_cloud", name="inactive", is_active=False),
        ]

        result = build_providers_from_accounts(accounts)

        assert len(result) == 1
        mock_build.assert_called_once()

    @patch("infraverse.sync.providers.build_provider")
    def test_skips_unknown_provider_type(self, mock_build):
        mock_build.return_value = None
        accounts = [_make_account("aws")]

        result = build_providers_from_accounts(accounts)

        assert result == []

    @patch("infraverse.sync.providers.build_provider")
    def test_skips_on_init_error(self, mock_build):
        mock_build.side_effect = RuntimeError("connection refused")
        accounts = [_make_account("yandex_cloud")]

        result = build_providers_from_accounts(accounts)

        assert result == []

    @patch("infraverse.sync.providers.build_provider")
    def test_mixed_active_inactive_and_error(self, mock_build):
        """Active account succeeds, inactive skipped, error account skipped."""
        mock_build.side_effect = [
            (MagicMock(), YC_PROFILE),
            RuntimeError("bad creds"),
        ]
        accounts = [
            _make_account("yandex_cloud", name="good", is_active=True),
            _make_account("yandex_cloud", name="inactive", is_active=False),
            _make_account("yandex_cloud", name="bad", is_active=True),
        ]

        result = build_providers_from_accounts(accounts)

        assert len(result) == 1


class TestBuildZabbixClient:
    """Tests for build_zabbix_client() shared function."""

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_with_infraverse_config(self, mock_zabbix_cls):
        mock_client = MagicMock()
        mock_zabbix_cls.return_value = mock_client

        infraverse_config = SimpleNamespace(
            monitoring_configured=True,
            monitoring=SimpleNamespace(
                zabbix_url="https://zabbix.config.com/api",
                zabbix_username="config-user",
                zabbix_password="config-pass",
            ),
        )
        result = build_zabbix_client(infraverse_config=infraverse_config)

        assert result is mock_client
        mock_zabbix_cls.assert_called_once_with(
            url="https://zabbix.config.com/api",
            username="config-user",
            password="config-pass",
        )

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_with_legacy_config(self, mock_zabbix_cls):
        mock_client = MagicMock()
        mock_zabbix_cls.return_value = mock_client

        legacy_config = SimpleNamespace(
            zabbix_configured=True,
            zabbix_url="https://zabbix.env.com",
            zabbix_user="Admin",
            zabbix_password="zabbix-pass",
        )
        result = build_zabbix_client(legacy_config=legacy_config)

        assert result is mock_client
        mock_zabbix_cls.assert_called_once_with(
            url="https://zabbix.env.com",
            username="Admin",
            password="zabbix-pass",
        )

    def test_returns_none_when_no_config(self):
        assert build_zabbix_client() is None

    def test_returns_none_when_infraverse_no_monitoring(self):
        infraverse_config = SimpleNamespace(monitoring_configured=False)
        assert build_zabbix_client(infraverse_config=infraverse_config) is None

    def test_returns_none_when_legacy_not_configured(self):
        legacy_config = SimpleNamespace(zabbix_configured=False)
        assert build_zabbix_client(legacy_config=legacy_config) is None

    def test_infraverse_config_prevents_legacy_fallback(self):
        """When infraverse_config is set but has no monitoring, don't use legacy_config."""
        infraverse_config = SimpleNamespace(monitoring_configured=False)
        legacy_config = SimpleNamespace(
            zabbix_configured=True,
            zabbix_url="https://zabbix.env.com",
            zabbix_user="Admin",
            zabbix_password="pass",
        )
        result = build_zabbix_client(
            infraverse_config=infraverse_config,
            legacy_config=legacy_config,
        )
        assert result is None

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_infraverse_config_error_returns_none(self, mock_zabbix_cls):
        mock_zabbix_cls.side_effect = RuntimeError("connection refused")

        infraverse_config = SimpleNamespace(
            monitoring_configured=True,
            monitoring=SimpleNamespace(
                zabbix_url="https://zabbix.com",
                zabbix_username="u",
                zabbix_password="p",
            ),
        )
        result = build_zabbix_client(infraverse_config=infraverse_config)
        assert result is None

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_legacy_config_error_returns_none(self, mock_zabbix_cls):
        mock_zabbix_cls.side_effect = RuntimeError("connection refused")

        legacy_config = SimpleNamespace(
            zabbix_configured=True,
            zabbix_url="https://zabbix.com",
            zabbix_user="u",
            zabbix_password="p",
        )
        result = build_zabbix_client(legacy_config=legacy_config)
        assert result is None

    @patch("infraverse.providers.zabbix.ZabbixClient")
    def test_infraverse_takes_precedence_over_legacy(self, mock_zabbix_cls):
        mock_client = MagicMock()
        mock_zabbix_cls.return_value = mock_client

        infraverse_config = SimpleNamespace(
            monitoring_configured=True,
            monitoring=SimpleNamespace(
                zabbix_url="https://zabbix.config.com",
                zabbix_username="config-user",
                zabbix_password="config-pass",
            ),
        )
        legacy_config = SimpleNamespace(
            zabbix_configured=True,
            zabbix_url="https://zabbix.env.com",
            zabbix_user="env-user",
            zabbix_password="env-pass",
        )
        build_zabbix_client(
            infraverse_config=infraverse_config,
            legacy_config=legacy_config,
        )

        mock_zabbix_cls.assert_called_once_with(
            url="https://zabbix.config.com",
            username="config-user",
            password="config-pass",
        )
