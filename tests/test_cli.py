"""Tests for the infraverse CLI entry point."""

import argparse
from unittest.mock import patch, MagicMock

import pytest

from infraverse.cli import build_parser, cmd_db_init, cmd_db_seed, cmd_sync, cmd_serve, main


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
        assert args.host == "0.0.0.0"
        assert args.port == 8000

    def test_serve_custom_host(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--host", "127.0.0.1"])
        assert args.host == "127.0.0.1"

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

    @patch("infraverse.config.Config.from_env")
    def test_cmd_sync_calls_engine(self, mock_from_env):
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

    @patch("infraverse.config.Config.from_env")
    def test_cmd_sync_passes_dry_run(self, mock_from_env):
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


class TestCmdServe:
    """Tests for serve command execution."""

    @patch("infraverse.config.Config.from_env")
    @patch("uvicorn.run")
    def test_cmd_serve_starts_uvicorn(self, mock_uvicorn_run, mock_from_env):
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///test.db"
        mock_from_env.return_value = mock_config

        with patch("infraverse.web.app.create_app") as mock_create_app:
            mock_app = MagicMock()
            mock_create_app.return_value = mock_app

            args = argparse.Namespace(host="127.0.0.1", port=9000)
            cmd_serve(args)

        mock_uvicorn_run.assert_called_once_with(mock_app, host="127.0.0.1", port=9000)

    @patch("infraverse.config.Config.from_env")
    @patch("uvicorn.run")
    def test_cmd_serve_uses_config_db_url(self, mock_uvicorn_run, mock_from_env):
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///custom.db"
        mock_from_env.return_value = mock_config

        with patch("infraverse.web.app.create_app") as mock_create_app:
            mock_create_app.return_value = MagicMock()
            args = argparse.Namespace(host="0.0.0.0", port=8000)
            cmd_serve(args)

        mock_create_app.assert_called_once_with(database_url="sqlite:///custom.db")


class TestCmdDbInit:
    """Tests for db init command execution."""

    @patch("infraverse.config.Config.from_env")
    def test_cmd_db_init_creates_tables(self, mock_from_env):
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///:memory:"
        mock_from_env.return_value = mock_config

        with patch("infraverse.db.engine.create_engine") as mock_create_engine, \
             patch("infraverse.db.engine.init_db") as mock_init_db:
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine

            args = argparse.Namespace()
            cmd_db_init(args)

        mock_create_engine.assert_called_once_with("sqlite:///:memory:")
        mock_init_db.assert_called_once_with(mock_engine)


class TestCmdDbSeed:
    """Tests for db seed command execution."""

    @patch("infraverse.config.Config.from_env")
    def test_cmd_db_seed_creates_default_tenant(self, mock_from_env):
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///:memory:"
        mock_from_env.return_value = mock_config

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf:
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

    @patch("infraverse.config.Config.from_env")
    def test_cmd_db_seed_skips_if_exists(self, mock_from_env):
        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///:memory:"
        mock_from_env.return_value = mock_config

        with patch("infraverse.db.engine.create_engine") as mock_ce, \
             patch("infraverse.db.engine.init_db"), \
             patch("infraverse.db.engine.create_session_factory") as mock_sf:
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
