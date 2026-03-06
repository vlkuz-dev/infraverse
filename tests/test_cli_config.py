"""Tests for CLI --config flag and config-file-driven ingestion."""

import argparse
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml

from infraverse.cli import (
    build_parser,
    cmd_sync,
    _build_provider_from_account,
    _ingest_to_db_with_config,
)
from infraverse.config_file import (
    CloudAccountConfig,
    InfraverseConfig,
    MonitoringConfig,
    TenantConfig,
)


# --- Parser tests ---


class TestParserConfigFlag:
    """Tests for --config / -c flag on sync and serve commands."""

    def test_sync_accepts_config_flag(self):
        parser = build_parser()
        args = parser.parse_args(["sync", "--config", "/path/to/config.yaml"])
        assert args.config == "/path/to/config.yaml"

    def test_sync_accepts_short_config_flag(self):
        parser = build_parser()
        args = parser.parse_args(["sync", "-c", "/path/to/config.yaml"])
        assert args.config == "/path/to/config.yaml"

    def test_sync_config_default_is_none(self):
        parser = build_parser()
        args = parser.parse_args(["sync"])
        assert args.config is None

    def test_serve_accepts_config_flag(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--config", "/path/to/config.yaml"])
        assert args.config == "/path/to/config.yaml"

    def test_serve_accepts_short_config_flag(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "-c", "/path/to/config.yaml"])
        assert args.config == "/path/to/config.yaml"

    def test_serve_config_default_is_none(self):
        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.config is None

    def test_sync_config_with_other_flags(self):
        parser = build_parser()
        args = parser.parse_args(
            ["sync", "--config", "cfg.yaml", "--dry-run", "--no-batch"]
        )
        assert args.config == "cfg.yaml"
        assert args.dry_run is True
        assert args.no_batch is True


# --- _build_provider_from_account tests ---


class TestBuildProviderFromAccount:
    """Tests for building CloudProvider instances from CloudAccount records."""

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_builds_yandex_client(self, mock_yc_cls):
        account = MagicMock()
        account.provider_type = "yandex_cloud"
        account.config = {"token": "yc-secret-token"}

        mock_yc = MagicMock()
        mock_yc_cls.return_value = mock_yc

        result = _build_provider_from_account(account)

        mock_yc_cls.assert_called_once_with(token="yc-secret-token")
        assert result is mock_yc

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    def test_builds_vcloud_client(self, mock_vcd_cls):
        account = MagicMock()
        account.provider_type = "vcloud"
        account.config = {
            "url": "https://vcd.example.com",
            "username": "admin",
            "password": "secret",
            "org": "MyOrg",
        }

        mock_vcd = MagicMock()
        mock_vcd_cls.return_value = mock_vcd

        result = _build_provider_from_account(account)

        mock_vcd_cls.assert_called_once_with(
            url="https://vcd.example.com",
            username="admin",
            password="secret",
            org="MyOrg",
        )
        assert result is mock_vcd

    @patch("infraverse.providers.vcloud.VCloudDirectorClient")
    def test_vcloud_defaults_org_to_system(self, mock_vcd_cls):
        account = MagicMock()
        account.provider_type = "vcloud"
        account.config = {
            "url": "https://vcd.example.com",
            "username": "admin",
            "password": "secret",
        }

        _build_provider_from_account(account)

        call_kwargs = mock_vcd_cls.call_args
        assert call_kwargs.kwargs["org"] == "System"

    def test_unknown_provider_raises(self):
        account = MagicMock()
        account.provider_type = "aws"
        account.config = {}

        with pytest.raises(ValueError, match="Unknown provider type: aws"):
            _build_provider_from_account(account)


# --- _ingest_to_db_with_config tests ---


class TestIngestToDbWithConfig:
    """Tests for config-file-driven DB ingestion."""

    def _make_infraverse_config(self, tenants=None, monitoring=None):
        t = {}
        for tname, accounts in (tenants or {}).items():
            accs = [
                CloudAccountConfig(name=a[0], provider=a[1], credentials=a[2] if len(a) > 2 else {})
                for a in accounts
            ]
            t[tname] = TenantConfig(name=tname, cloud_accounts=accs)
        return InfraverseConfig(tenants=t, monitoring=monitoring)

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_calls_sync_config_to_db(self, mock_yc_cls):
        config = self._make_infraverse_config(
            tenants={"acme": [("acme-yc", "yandex_cloud", {"token": "t1"})]}
        )
        mock_yc_cls.return_value = MagicMock()

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.sync.config_sync.sync_config_to_db") as mock_sync_cfg, \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls:
            mock_ce.return_value = MagicMock()
            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            mock_sync_cfg.return_value = MagicMock()

            # Mock repo to return active accounts
            with patch("infraverse.db.repository.Repository") as mock_repo_cls:
                mock_repo = MagicMock()
                mock_account = MagicMock()
                mock_account.id = 1
                mock_account.is_active = True
                mock_account.provider_type = "yandex_cloud"
                mock_account.config = {"token": "t1"}
                mock_account.name = "acme-yc"
                mock_repo.list_cloud_accounts.return_value = [mock_account]
                mock_repo_cls.return_value = mock_repo

                mock_ingestor = MagicMock()
                mock_ingestor.ingest_all.return_value = {}
                mock_ingestor_cls.return_value = mock_ingestor

                _ingest_to_db_with_config(config)

            mock_sync_cfg.assert_called_once_with(config, mock_session)

    @patch("infraverse.providers.yandex.YandexCloudClient")
    def test_builds_providers_from_active_accounts(self, mock_yc_cls):
        config = self._make_infraverse_config(
            tenants={"acme": [("acme-yc", "yandex_cloud", {"token": "t1"})]}
        )
        mock_yc = MagicMock()
        mock_yc_cls.return_value = mock_yc

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.sync.config_sync.sync_config_to_db"), \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls, \
             patch("infraverse.db.repository.Repository") as mock_repo_cls:
            mock_ce.return_value = MagicMock()
            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            active_account = MagicMock()
            active_account.id = 1
            active_account.is_active = True
            active_account.provider_type = "yandex_cloud"
            active_account.config = {"token": "t1"}
            active_account.name = "acme-yc"

            inactive_account = MagicMock()
            inactive_account.id = 2
            inactive_account.is_active = False
            inactive_account.provider_type = "yandex_cloud"
            inactive_account.config = {"token": "old"}
            inactive_account.name = "old-yc"

            mock_repo = MagicMock()
            mock_repo.list_cloud_accounts.return_value = [active_account, inactive_account]
            mock_repo_cls.return_value = mock_repo

            mock_ingestor = MagicMock()
            mock_ingestor.ingest_all.return_value = {}
            mock_ingestor_cls.return_value = mock_ingestor

            _ingest_to_db_with_config(config)

            # Only active account should be in providers
            providers = mock_ingestor.ingest_all.call_args[0][0]
            assert 1 in providers
            assert 2 not in providers

    def test_includes_zabbix_when_monitoring_configured(self):
        monitoring = MonitoringConfig(
            zabbix_url="https://zabbix.example.com/api_jsonrpc.php",
            zabbix_username="admin",
            zabbix_password="secret",
        )
        config = self._make_infraverse_config(
            tenants={"acme": [("acme-yc", "yandex_cloud", {"token": "t1"})]},
            monitoring=monitoring,
        )

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.sync.config_sync.sync_config_to_db"), \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls, \
             patch("infraverse.db.repository.Repository") as mock_repo_cls, \
             patch("infraverse.providers.yandex.YandexCloudClient"), \
             patch("infraverse.providers.zabbix.ZabbixClient") as mock_zabbix_cls:
            mock_ce.return_value = MagicMock()
            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            mock_account = MagicMock()
            mock_account.id = 1
            mock_account.is_active = True
            mock_account.provider_type = "yandex_cloud"
            mock_account.config = {"token": "t1"}
            mock_account.name = "acme-yc"
            mock_repo = MagicMock()
            mock_repo.list_cloud_accounts.return_value = [mock_account]
            mock_repo_cls.return_value = mock_repo

            mock_zabbix = MagicMock()
            mock_zabbix_cls.return_value = mock_zabbix

            mock_ingestor = MagicMock()
            mock_ingestor.ingest_all.return_value = {}
            mock_ingestor_cls.return_value = mock_ingestor

            _ingest_to_db_with_config(config)

            mock_zabbix_cls.assert_called_once_with(
                url="https://zabbix.example.com/api_jsonrpc.php",
                username="admin",
                password="secret",
            )
            zabbix_arg = mock_ingestor.ingest_all.call_args[0][1]
            assert zabbix_arg is mock_zabbix

    def test_no_zabbix_when_monitoring_not_configured(self):
        config = self._make_infraverse_config(
            tenants={"acme": [("acme-yc", "yandex_cloud", {"token": "t1"})]}
        )

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.sync.config_sync.sync_config_to_db"), \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls, \
             patch("infraverse.db.repository.Repository") as mock_repo_cls, \
             patch("infraverse.providers.yandex.YandexCloudClient"):
            mock_ce.return_value = MagicMock()
            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            mock_account = MagicMock()
            mock_account.id = 1
            mock_account.is_active = True
            mock_account.provider_type = "yandex_cloud"
            mock_account.config = {"token": "t1"}
            mock_account.name = "acme-yc"
            mock_repo = MagicMock()
            mock_repo.list_cloud_accounts.return_value = [mock_account]
            mock_repo_cls.return_value = mock_repo

            mock_ingestor = MagicMock()
            mock_ingestor.ingest_all.return_value = {}
            mock_ingestor_cls.return_value = mock_ingestor

            _ingest_to_db_with_config(config)

            zabbix_arg = mock_ingestor.ingest_all.call_args[0][1]
            assert zabbix_arg is None

    def test_uses_provided_database_url(self):
        config = self._make_infraverse_config(
            tenants={"acme": [("acme-yc", "yandex_cloud", {"token": "t1"})]}
        )

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.sync.config_sync.sync_config_to_db"), \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls, \
             patch("infraverse.db.repository.Repository") as mock_repo_cls, \
             patch("infraverse.providers.yandex.YandexCloudClient"):
            mock_ce.return_value = MagicMock()
            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            mock_repo = MagicMock()
            mock_repo.list_cloud_accounts.return_value = []
            mock_repo_cls.return_value = mock_repo

            mock_ingestor = MagicMock()
            mock_ingestor.ingest_all.return_value = {}
            mock_ingestor_cls.return_value = mock_ingestor

            _ingest_to_db_with_config(config, database_url="sqlite:///custom.db")

            mock_ce.assert_called_once_with("sqlite:///custom.db")


# --- cmd_sync with --config tests ---


class TestCmdSyncWithConfig:
    """Tests for cmd_sync when --config is provided."""

    def _write_config_file(self, config_dict):
        """Write a YAML config file and return its path."""
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        )
        yaml.dump(config_dict, f)
        f.close()
        return f.name

    def test_cmd_sync_with_config_calls_ingest_with_config(self):
        config_data = {
            "tenants": {
                "acme": {
                    "cloud_accounts": [
                        {"name": "acme-yc", "provider": "yandex_cloud", "token": "t1"}
                    ]
                }
            }
        }
        config_path = self._write_config_file(config_data)
        try:
            with patch("infraverse.cli._ingest_to_db_with_config") as mock_ingest_cfg, \
                 patch("infraverse.config.Config.from_env") as mock_from_env, \
                 patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
                mock_config = MagicMock()
                mock_from_env.return_value = mock_config
                mock_engine = MagicMock()
                mock_engine.run.return_value = {}
                mock_engine_cls.return_value = mock_engine

                args = argparse.Namespace(
                    config=config_path, dry_run=False, no_batch=False, no_cleanup=False
                )
                cmd_sync(args)

                mock_ingest_cfg.assert_called_once()
                # First arg should be InfraverseConfig
                infra_config = mock_ingest_cfg.call_args[0][0]
                assert "acme" in infra_config.tenants
        finally:
            os.unlink(config_path)

    def test_cmd_sync_with_config_still_runs_netbox_sync(self):
        config_data = {
            "tenants": {
                "acme": {
                    "cloud_accounts": [
                        {"name": "acme-yc", "provider": "yandex_cloud", "token": "t1"}
                    ]
                }
            }
        }
        config_path = self._write_config_file(config_data)
        try:
            with patch("infraverse.cli._ingest_to_db_with_config"), \
                 patch("infraverse.config.Config.from_env") as mock_from_env, \
                 patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
                mock_config = MagicMock()
                mock_from_env.return_value = mock_config
                mock_engine = MagicMock()
                mock_engine.run.return_value = {}
                mock_engine_cls.return_value = mock_engine

                args = argparse.Namespace(
                    config=config_path, dry_run=False, no_batch=False, no_cleanup=False
                )
                cmd_sync(args)

                mock_engine.run.assert_called_once()
        finally:
            os.unlink(config_path)

    def test_cmd_sync_with_config_skips_netbox_if_env_missing(self):
        config_data = {
            "tenants": {
                "acme": {
                    "cloud_accounts": [
                        {"name": "acme-yc", "provider": "yandex_cloud", "token": "t1"}
                    ]
                }
            }
        }
        config_path = self._write_config_file(config_data)
        try:
            with patch("infraverse.cli._ingest_to_db_with_config"), \
                 patch("infraverse.config.Config.from_env", side_effect=ValueError("Missing")):
                args = argparse.Namespace(
                    config=config_path, dry_run=False, no_batch=False, no_cleanup=False
                )
                # Should NOT exit - config file mode works without NetBox env vars
                cmd_sync(args)
        finally:
            os.unlink(config_path)

    def test_cmd_sync_with_config_invalid_file_exits(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: true\n")  # No tenants key
            config_path = f.name
        try:
            args = argparse.Namespace(
                config=config_path, dry_run=False, no_batch=False, no_cleanup=False
            )
            with pytest.raises(SystemExit) as exc_info:
                cmd_sync(args)
            assert exc_info.value.code == 1
        finally:
            os.unlink(config_path)

    def test_cmd_sync_with_config_missing_file_exits(self):
        args = argparse.Namespace(
            config="/nonexistent/config.yaml", dry_run=False, no_batch=False, no_cleanup=False
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_sync(args)
        assert exc_info.value.code == 1


# --- Backward compatibility tests ---


class TestBackwardCompatibility:
    """Tests that CLI works without --config using current env var behavior."""

    @patch("infraverse.cli._ingest_to_db")
    @patch("infraverse.config.Config.from_env")
    def test_sync_without_config_uses_env_vars(self, mock_from_env, mock_ingest):
        """Without --config, cmd_sync should use Config.from_env and _ingest_to_db."""
        mock_config = MagicMock()
        mock_from_env.return_value = mock_config

        with patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.return_value = {}
            mock_engine_cls.return_value = mock_engine

            args = argparse.Namespace(
                config=None, dry_run=False, no_batch=False, no_cleanup=False
            )
            cmd_sync(args)

        mock_from_env.assert_called_once_with(dry_run=False)
        mock_ingest.assert_called_once_with(mock_config)

    @patch("infraverse.cli._ingest_to_db")
    @patch("infraverse.config.Config.from_env")
    def test_sync_without_config_passes_dry_run(self, mock_from_env, mock_ingest):
        mock_config = MagicMock()
        mock_from_env.return_value = mock_config

        with patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.return_value = {}
            mock_engine_cls.return_value = mock_engine

            args = argparse.Namespace(
                config=None, dry_run=True, no_batch=True, no_cleanup=True
            )
            cmd_sync(args)

        mock_from_env.assert_called_once_with(dry_run=True)

    def test_sync_without_config_exits_on_missing_env(self):
        """Without --config, missing env vars should exit."""
        with patch("infraverse.config.Config.from_env", side_effect=ValueError("Missing")):
            args = argparse.Namespace(
                config=None, dry_run=False, no_batch=False, no_cleanup=False
            )
            with pytest.raises(SystemExit) as exc_info:
                cmd_sync(args)
            assert exc_info.value.code == 1
