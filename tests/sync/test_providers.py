"""Tests for infraverse.sync.providers module."""

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from infraverse.sync.providers import build_provider, build_providers_from_accounts
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
