"""Tests for the infraverse CLI entry point."""

import argparse
from unittest.mock import patch, MagicMock

import pytest

from infraverse.cli import (
    build_parser, cmd_db_init, cmd_db_seed, cmd_sync, cmd_serve, main,
    _ingest_to_db, _ensure_cloud_account,
)


class TestBuildParser:
    """Tests for argument parser construction."""

    def test_parser_is_argparse(self):
        parser = build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_prog_name(self):
        parser = build_parser()
        assert parser.prog == "infraverse"

    def test_no_command_gives_none(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None


class TestSyncCommand:
    """Tests for sync subcommand parsing."""

    def test_sync_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["sync"])
        assert args.command == "sync"
        assert args.dry_run is False
        assert args.no_batch is False
        assert args.no_cleanup is False

    def test_sync_dry_run(self):
        parser = build_parser()
        args = parser.parse_args(["sync", "--dry-run"])
        assert args.dry_run is True

    def test_sync_no_batch(self):
        parser = build_parser()
        args = parser.parse_args(["sync", "--no-batch"])
        assert args.no_batch is True

    def test_sync_no_cleanup(self):
        parser = build_parser()
        args = parser.parse_args(["sync", "--no-cleanup"])
        assert args.no_cleanup is True

    def test_sync_all_flags(self):
        parser = build_parser()
        args = parser.parse_args(["sync", "--dry-run", "--no-batch", "--no-cleanup"])
        assert args.dry_run is True
        assert args.no_batch is True
        assert args.no_cleanup is True


class TestServeCommand:
    """Tests for serve subcommand parsing."""

    def test_serve_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == "127.0.0.1"
        assert args.port == 8000

    def test_serve_custom_host(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--host", "0.0.0.0"])
        assert args.host == "0.0.0.0"

    def test_serve_custom_port(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--port", "9000"])
        assert args.port == 9000


class TestDbCommand:
    """Tests for db subcommand parsing."""

    def test_db_init(self):
        parser = build_parser()
        args = parser.parse_args(["db", "init"])
        assert args.command == "db"
        assert args.db_command == "init"

    def test_db_seed(self):
        parser = build_parser()
        args = parser.parse_args(["db", "seed"])
        assert args.command == "db"
        assert args.db_command == "seed"

    def test_db_no_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["db"])
        assert args.command == "db"
        assert args.db_command is None


class TestCmdSync:
    """Tests for sync command execution."""

    @patch("infraverse.cli._ingest_to_db")
    @patch("infraverse.config.Config.from_env")
    def test_cmd_sync_calls_engine(self, mock_from_env, mock_ingest):
        mock_config = MagicMock()
        mock_from_env.return_value = mock_config

        with patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.return_value = {"created": 5}
            mock_engine_cls.return_value = mock_engine

            args = argparse.Namespace(dry_run=False, no_batch=False, no_cleanup=False)
            cmd_sync(args)

        mock_config.setup_logging.assert_called_once()
        mock_engine.run.assert_called_once_with(use_batch=True, cleanup=True)

    @patch("infraverse.cli._ingest_to_db")
    @patch("infraverse.config.Config.from_env")
    def test_cmd_sync_passes_dry_run(self, mock_from_env, mock_ingest):
        mock_config = MagicMock()
        mock_from_env.return_value = mock_config

        with patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.return_value = {}
            mock_engine_cls.return_value = mock_engine

            args = argparse.Namespace(dry_run=True, no_batch=True, no_cleanup=True)
            cmd_sync(args)

        mock_from_env.assert_called_once_with(dry_run=True)
        mock_engine.run.assert_called_once_with(use_batch=False, cleanup=False)

    def test_cmd_sync_config_error_exits(self):
        with patch("infraverse.config.Config.from_env", side_effect=ValueError("Missing YC_TOKEN")):
            args = argparse.Namespace(dry_run=False, no_batch=False, no_cleanup=False)
            with pytest.raises(SystemExit) as exc_info:
                cmd_sync(args)
            assert exc_info.value.code == 1

    @patch("infraverse.cli._ingest_to_db")
    @patch("infraverse.config.Config.from_env")
    def test_cmd_sync_engine_error_exits(self, mock_from_env, mock_ingest):
        mock_config = MagicMock()
        mock_from_env.return_value = mock_config

        with patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.side_effect = RuntimeError("API down")
            mock_engine_cls.return_value = mock_engine

            args = argparse.Namespace(dry_run=False, no_batch=False, no_cleanup=False)
            with pytest.raises(SystemExit) as exc_info:
                cmd_sync(args)
            assert exc_info.value.code == 1

    @patch("infraverse.config.Config.from_env")
    def test_cmd_sync_calls_ingest_to_db(self, mock_from_env):
        mock_config = MagicMock()
        mock_from_env.return_value = mock_config

        with patch("infraverse.cli._ingest_to_db") as mock_ingest, \
             patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.return_value = {}
            mock_engine_cls.return_value = mock_engine

            args = argparse.Namespace(dry_run=False, no_batch=False, no_cleanup=False)
            cmd_sync(args)

        mock_ingest.assert_called_once_with(mock_config)

    @patch("infraverse.config.Config.from_env")
    def test_cmd_sync_continues_on_ingest_error(self, mock_from_env):
        """Sync to NetBox should proceed even if DB ingestion fails."""
        mock_config = MagicMock()
        mock_from_env.return_value = mock_config

        with patch("infraverse.cli._ingest_to_db", side_effect=RuntimeError("DB error")), \
             patch("infraverse.sync.engine.SyncEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.run.return_value = {}
            mock_engine_cls.return_value = mock_engine

            args = argparse.Namespace(dry_run=False, no_batch=False, no_cleanup=False)
            cmd_sync(args)

        mock_engine.run.assert_called_once()


class TestCmdServe:
    """Tests for serve command execution."""

    @patch("uvicorn.run")
    def test_cmd_serve_starts_uvicorn(self, mock_uvicorn_run):
        with patch("infraverse.web.app.create_app") as mock_create_app, \
             patch.dict("os.environ", {"DATABASE_URL": "sqlite:///test.db"}):
            mock_app = MagicMock()
            mock_create_app.return_value = mock_app

            args = argparse.Namespace(host="127.0.0.1", port=9000)
            cmd_serve(args)

        mock_uvicorn_run.assert_called_once_with(mock_app, host="127.0.0.1", port=9000)

    @patch("uvicorn.run")
    def test_cmd_serve_uses_database_url_env(self, mock_uvicorn_run):
        with patch("infraverse.web.app.create_app") as mock_create_app, \
             patch.dict("os.environ", {"DATABASE_URL": "sqlite:///custom.db"}):
            mock_create_app.return_value = MagicMock()
            args = argparse.Namespace(host="127.0.0.1", port=8000)
            cmd_serve(args)

        mock_create_app.assert_called_once()
        call_kwargs = mock_create_app.call_args
        assert call_kwargs.kwargs["database_url"] == "sqlite:///custom.db"
        # config is a SimpleNamespace with external link URLs (not None)
        assert call_kwargs.kwargs["config"].sync_interval_minutes == 0

    @patch("uvicorn.run")
    def test_cmd_serve_does_not_require_cloud_creds(self, mock_uvicorn_run):
        """Serve should work without YC_TOKEN, NETBOX_URL, NETBOX_TOKEN."""
        env = {"DATABASE_URL": "sqlite:///test.db"}
        with patch("infraverse.web.app.create_app") as mock_create_app, \
             patch.dict("os.environ", env, clear=True):
            mock_create_app.return_value = MagicMock()
            args = argparse.Namespace(host="127.0.0.1", port=8000)
            cmd_serve(args)

        mock_create_app.assert_called_once()


class TestCmdDbInit:
    """Tests for db init command execution."""

    def test_cmd_db_init_creates_tables(self):
        with patch("infraverse.db.engine.create_engine") as mock_create_engine, \
             patch("infraverse.db.engine.init_db") as mock_init_db, \
             patch.dict("os.environ", {"DATABASE_URL": "sqlite:///:memory:"}):
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine

            args = argparse.Namespace()
            cmd_db_init(args)

        mock_create_engine.assert_called_once_with("sqlite:///:memory:")
        mock_init_db.assert_called_once_with(mock_engine)

    def test_cmd_db_init_does_not_require_cloud_creds(self):
        """db init should work without YC_TOKEN, NETBOX_URL, NETBOX_TOKEN."""
        env = {"DATABASE_URL": "sqlite:///:memory:"}
        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch.dict("os.environ", env, clear=True):
            mock_ce.return_value = MagicMock()
            args = argparse.Namespace()
            cmd_db_init(args)

        mock_ce.assert_called_once()


class TestCmdDbSeed:
    """Tests for db seed command execution."""

    def test_cmd_db_seed_creates_default_tenant(self):
        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch.dict("os.environ", {"DATABASE_URL": "sqlite:///:memory:"}):
            mock_engine = MagicMock()
            mock_ce.return_value = mock_engine

            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            with patch("infraverse.db.repository.Repository") as mock_repo_cls:
                mock_repo = MagicMock()
                mock_repo.get_tenant_by_name.return_value = None
                mock_tenant = MagicMock()
                mock_tenant.id = 1
                mock_repo.create_tenant.return_value = mock_tenant
                mock_repo_cls.return_value = mock_repo

                args = argparse.Namespace()
                cmd_db_seed(args)

            mock_repo.create_tenant.assert_called_once_with(
                name="Default", description="Default tenant"
            )
            mock_session.commit.assert_called_once()

    def test_cmd_db_seed_skips_if_exists(self):
        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch.dict("os.environ", {"DATABASE_URL": "sqlite:///:memory:"}):
            mock_ce.return_value = MagicMock()

            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            with patch("infraverse.db.repository.Repository") as mock_repo_cls:
                mock_repo = MagicMock()
                existing_tenant = MagicMock()
                existing_tenant.id = 42
                mock_repo.get_tenant_by_name.return_value = existing_tenant
                mock_repo_cls.return_value = mock_repo

                args = argparse.Namespace()
                cmd_db_seed(args)

            mock_repo.create_tenant.assert_not_called()
            mock_session.commit.assert_not_called()


class TestIngestToDb:
    """Tests for _ingest_to_db helper that populates DB during sync."""

    def test_ingest_creates_tenant_and_account(self):
        """_ingest_to_db should create default tenant and YC cloud account."""
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///:memory:"
        mock_config.yc_token = "test-token"
        mock_config.vcd_configured = False
        mock_config.zabbix_configured = False

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.db.repository.Repository") as mock_repo_cls, \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls, \
             patch("infraverse.providers.yandex.YandexCloudClient") as mock_yc_cls:
            mock_ce.return_value = MagicMock()

            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            mock_repo = MagicMock()
            mock_repo.get_tenant_by_name.return_value = None
            mock_tenant = MagicMock()
            mock_tenant.id = 1
            mock_repo.create_tenant.return_value = mock_tenant
            mock_repo.list_cloud_accounts_by_tenant.return_value = []
            mock_account = MagicMock()
            mock_account.id = 10
            mock_repo.create_cloud_account.return_value = mock_account
            mock_repo_cls.return_value = mock_repo

            mock_ingestor = MagicMock()
            mock_ingestor.ingest_all.return_value = {}
            mock_ingestor_cls.return_value = mock_ingestor

            mock_yc = MagicMock()
            mock_yc_cls.return_value = mock_yc

            _ingest_to_db(mock_config)

            mock_repo.create_tenant.assert_called_once_with(name="Default")
            mock_repo.create_cloud_account.assert_called_once_with(
                tenant_id=1, provider_type="yandex_cloud", name="Yandex Cloud",
            )
            mock_ingestor.ingest_all.assert_called_once_with({10: mock_yc}, None)

    def test_ingest_reuses_existing_tenant(self):
        """_ingest_to_db should reuse existing tenant, not create a new one."""
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///:memory:"
        mock_config.yc_token = "test-token"
        mock_config.vcd_configured = False
        mock_config.zabbix_configured = False

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.db.repository.Repository") as mock_repo_cls, \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls, \
             patch("infraverse.providers.yandex.YandexCloudClient"):
            mock_ce.return_value = MagicMock()

            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            existing_tenant = MagicMock()
            existing_tenant.id = 5
            mock_repo = MagicMock()
            mock_repo.get_tenant_by_name.return_value = existing_tenant
            mock_repo.list_cloud_accounts_by_tenant.return_value = []
            mock_account = MagicMock()
            mock_account.id = 20
            mock_repo.create_cloud_account.return_value = mock_account
            mock_repo_cls.return_value = mock_repo

            mock_ingestor = MagicMock()
            mock_ingestor_cls.return_value = mock_ingestor

            _ingest_to_db(mock_config)

            mock_repo.create_tenant.assert_not_called()

    def test_ingest_includes_vcloud_when_configured(self):
        """_ingest_to_db should include vCloud when configured."""
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///:memory:"
        mock_config.yc_token = "test-token"
        mock_config.vcd_configured = True
        mock_config.vcd_url = "https://vcd.example.com"
        mock_config.vcd_user = "admin"
        mock_config.vcd_password = "pass"
        mock_config.vcd_org = "MyOrg"
        mock_config.zabbix_configured = False

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.db.repository.Repository") as mock_repo_cls, \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls, \
             patch("infraverse.providers.yandex.YandexCloudClient"), \
             patch("infraverse.providers.vcloud.VCloudDirectorClient"):
            mock_ce.return_value = MagicMock()

            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            mock_tenant = MagicMock()
            mock_tenant.id = 1
            mock_repo = MagicMock()
            mock_repo.get_tenant_by_name.return_value = mock_tenant
            yc_account = MagicMock()
            yc_account.id = 10
            yc_account.provider_type = "yandex_cloud"
            yc_account.name = "Yandex Cloud"
            vcd_account = MagicMock()
            vcd_account.id = 11
            mock_repo.list_cloud_accounts_by_tenant.side_effect = [
                [yc_account], [yc_account],
            ]
            mock_repo.create_cloud_account.return_value = vcd_account
            mock_repo_cls.return_value = mock_repo

            mock_ingestor = MagicMock()
            mock_ingestor_cls.return_value = mock_ingestor

            _ingest_to_db(mock_config)

            # Should have called ingest_all with 2 providers
            call_args = mock_ingestor.ingest_all.call_args
            providers = call_args[0][0]
            assert len(providers) == 2
            assert 10 in providers
            assert 11 in providers

    def test_ingest_includes_zabbix_when_configured(self):
        """_ingest_to_db should pass ZabbixClient when configured."""
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///:memory:"
        mock_config.yc_token = "test-token"
        mock_config.vcd_configured = False
        mock_config.zabbix_configured = True
        mock_config.zabbix_url = "https://zabbix.example.com"
        mock_config.zabbix_user = "Admin"
        mock_config.zabbix_password = "zabbix"

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf, \
             patch("infraverse.db.repository.Repository") as mock_repo_cls, \
             patch("infraverse.sync.ingest.DataIngestor") as mock_ingestor_cls, \
             patch("infraverse.providers.yandex.YandexCloudClient"), \
             patch("infraverse.providers.zabbix.ZabbixClient") as mock_zabbix_cls:
            mock_ce.return_value = MagicMock()

            mock_session = MagicMock()
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = mock_session_factory

            mock_tenant = MagicMock()
            mock_tenant.id = 1
            mock_repo = MagicMock()
            mock_repo.get_tenant_by_name.return_value = mock_tenant
            mock_account = MagicMock()
            mock_account.id = 10
            mock_account.provider_type = "yandex_cloud"
            mock_account.name = "Yandex Cloud"
            mock_repo.list_cloud_accounts_by_tenant.return_value = [mock_account]
            mock_repo_cls.return_value = mock_repo

            mock_ingestor = MagicMock()
            mock_ingestor_cls.return_value = mock_ingestor

            mock_zabbix = MagicMock()
            mock_zabbix_cls.return_value = mock_zabbix

            _ingest_to_db(mock_config)

            call_args = mock_ingestor.ingest_all.call_args
            zabbix_arg = call_args[0][1]
            assert zabbix_arg is mock_zabbix


class TestEnsureCloudAccount:
    """Tests for _ensure_cloud_account helper."""

    def test_creates_new_account(self):
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts_by_tenant.return_value = []
        mock_account = MagicMock()
        mock_account.id = 1
        mock_repo.create_cloud_account.return_value = mock_account
        mock_session = MagicMock()

        result = _ensure_cloud_account(mock_repo, mock_session, 1, "yandex_cloud", "YC")
        assert result == mock_account
        mock_repo.create_cloud_account.assert_called_once()

    def test_reuses_existing_account(self):
        existing = MagicMock()
        existing.provider_type = "yandex_cloud"
        existing.name = "Yandex Cloud"
        mock_repo = MagicMock()
        mock_repo.list_cloud_accounts_by_tenant.return_value = [existing]
        mock_session = MagicMock()

        result = _ensure_cloud_account(
            mock_repo, mock_session, 1, "yandex_cloud", "Yandex Cloud",
        )
        assert result == existing
        mock_repo.create_cloud_account.assert_not_called()


class TestMain:
    """Tests for the main() entry point."""

    @patch("infraverse.cli.load_dotenv", create=True)
    def test_main_no_command_exits(self, mock_load_dotenv):
        with patch("dotenv.load_dotenv", mock_load_dotenv):
            with patch("sys.argv", ["infraverse"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    @patch("dotenv.load_dotenv")
    def test_main_loads_dotenv(self, mock_load_dotenv):
        with patch("sys.argv", ["infraverse"]):
            with pytest.raises(SystemExit):
                main()
        mock_load_dotenv.assert_called_once()

    @patch("dotenv.load_dotenv")
    @patch("infraverse.cli.cmd_sync")
    def test_main_dispatches_sync(self, mock_cmd_sync, mock_load_dotenv):
        with patch("sys.argv", ["infraverse", "sync", "--dry-run"]):
            main()
        mock_cmd_sync.assert_called_once()
        args = mock_cmd_sync.call_args[0][0]
        assert args.dry_run is True

    @patch("dotenv.load_dotenv")
    @patch("infraverse.cli.cmd_serve")
    def test_main_dispatches_serve(self, mock_cmd_serve, mock_load_dotenv):
        with patch("sys.argv", ["infraverse", "serve", "--port", "3000"]):
            main()
        mock_cmd_serve.assert_called_once()
        args = mock_cmd_serve.call_args[0][0]
        assert args.port == 3000

    @patch("dotenv.load_dotenv")
    @patch("infraverse.cli.cmd_db_init")
    def test_main_dispatches_db_init(self, mock_cmd_db_init, mock_load_dotenv):
        with patch("sys.argv", ["infraverse", "db", "init"]):
            main()
        mock_cmd_db_init.assert_called_once()

    @patch("dotenv.load_dotenv")
    @patch("infraverse.cli.cmd_db_seed")
    def test_main_dispatches_db_seed(self, mock_cmd_db_seed, mock_load_dotenv):
        with patch("sys.argv", ["infraverse", "db", "seed"]):
            main()
        mock_cmd_db_seed.assert_called_once()
