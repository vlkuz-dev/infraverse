"""Tests for CLI argument parsing and main entry point."""

import subprocess
import sys
from unittest.mock import patch, MagicMock

import pytest

import netbox_sync
from netbox_sync.cli import parse_args, main


class TestParseArgs:
    """Tests for parse_args()."""

    def test_defaults_no_subcommand(self):
        """No subcommand defaults to sync with default flags."""
        args = parse_args([])
        assert args.command == "sync"
        assert args.dry_run is False
        assert args.no_cleanup is False
        assert args.standard is False

    def test_explicit_sync(self):
        args = parse_args(["sync"])
        assert args.command == "sync"
        assert args.dry_run is False

    def test_sync_dry_run(self):
        args = parse_args(["sync", "--dry-run"])
        assert args.command == "sync"
        assert args.dry_run is True

    def test_dry_run_no_subcommand(self):
        """--dry-run without subcommand defaults to sync."""
        args = parse_args(["--dry-run"])
        assert args.command == "sync"
        assert args.dry_run is True

    def test_no_cleanup(self):
        args = parse_args(["--no-cleanup"])
        assert args.command == "sync"
        assert args.no_cleanup is True

    def test_standard(self):
        args = parse_args(["--standard"])
        assert args.command == "sync"
        assert args.standard is True

    def test_all_sync_flags(self):
        args = parse_args(["--dry-run", "--no-cleanup", "--standard"])
        assert args.command == "sync"
        assert args.dry_run is True
        assert args.no_cleanup is True
        assert args.standard is True

    def test_all_sync_flags_explicit(self):
        args = parse_args(["sync", "--dry-run", "--no-cleanup", "--standard"])
        assert args.command == "sync"
        assert args.dry_run is True
        assert args.no_cleanup is True
        assert args.standard is True

    def test_version(self):
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_unknown_flag_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--unknown"])
        assert exc_info.value.code == 2

    def test_serve_defaults(self):
        args = parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == "127.0.0.1"
        assert args.port == 8000

    def test_serve_custom_host_port(self):
        args = parse_args(["serve", "--host", "127.0.0.1", "--port", "9000"])
        assert args.command == "serve"
        assert args.host == "127.0.0.1"
        assert args.port == 9000

    def test_serve_custom_host(self):
        args = parse_args(["serve", "--host", "localhost"])
        assert args.host == "localhost"
        assert args.port == 8000

    def test_serve_custom_port(self):
        args = parse_args(["serve", "--port", "3000"])
        assert args.host == "127.0.0.1"
        assert args.port == 3000


class TestMain:
    """Tests for main() entry point."""

    @patch("netbox_sync.cli.SyncEngine")
    @patch("netbox_sync.cli.Config")
    @patch("netbox_sync.cli.load_dotenv")
    def test_main_default_flags(self, mock_dotenv, mock_config_cls, mock_engine_cls):
        mock_config = MagicMock()
        mock_config_cls.from_env.return_value = mock_config
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        main([])

        mock_dotenv.assert_called_once()
        mock_config_cls.from_env.assert_called_once_with(dry_run=False)
        mock_config.setup_logging.assert_called_once()
        mock_engine_cls.assert_called_once_with(mock_config)
        mock_engine.run.assert_called_once_with(use_batch=True, cleanup=True)

    @patch("netbox_sync.cli.SyncEngine")
    @patch("netbox_sync.cli.Config")
    @patch("netbox_sync.cli.load_dotenv")
    def test_main_dry_run(self, mock_dotenv, mock_config_cls, mock_engine_cls):
        mock_config = MagicMock()
        mock_config_cls.from_env.return_value = mock_config
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        main(["--dry-run"])

        mock_config_cls.from_env.assert_called_once_with(dry_run=True)

    @patch("netbox_sync.cli.SyncEngine")
    @patch("netbox_sync.cli.Config")
    @patch("netbox_sync.cli.load_dotenv")
    def test_main_standard_no_cleanup(self, mock_dotenv, mock_config_cls, mock_engine_cls):
        mock_config = MagicMock()
        mock_config_cls.from_env.return_value = mock_config
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        main(["--standard", "--no-cleanup"])

        mock_engine.run.assert_called_once_with(use_batch=False, cleanup=False)

    @patch("netbox_sync.cli.load_dotenv")
    def test_main_missing_config_exits(self, mock_dotenv):
        with patch("netbox_sync.cli.Config") as mock_config_cls:
            mock_config_cls.from_env.side_effect = ValueError("Missing YC_TOKEN")
            with pytest.raises(SystemExit) as exc_info:
                main([])
            assert exc_info.value.code == 1

    @patch("netbox_sync.cli.SyncEngine")
    @patch("netbox_sync.cli.Config")
    @patch("netbox_sync.cli.load_dotenv")
    def test_main_sync_failure_exits(self, mock_dotenv, mock_config_cls, mock_engine_cls):
        mock_config = MagicMock()
        mock_config_cls.from_env.return_value = mock_config
        mock_engine = MagicMock()
        mock_engine.run.side_effect = RuntimeError("connection refused")
        mock_engine_cls.return_value = mock_engine

        with pytest.raises(SystemExit) as exc_info:
            main(["--dry-run"])
        assert exc_info.value.code == 1

    @patch("netbox_sync.cli.SyncEngine")
    @patch("netbox_sync.cli.Config")
    @patch("netbox_sync.cli.load_dotenv")
    def test_main_explicit_sync_subcommand(self, mock_dotenv, mock_config_cls, mock_engine_cls):
        mock_config = MagicMock()
        mock_config_cls.from_env.return_value = mock_config
        mock_engine = MagicMock()
        mock_engine.run.return_value = {}
        mock_engine_cls.return_value = mock_engine

        main(["sync", "--dry-run"])

        mock_config_cls.from_env.assert_called_once_with(dry_run=True)
        mock_engine.run.assert_called_once_with(use_batch=True, cleanup=True)


class TestMainServe:
    """Tests for main() with serve subcommand."""

    @patch("netbox_sync.cli._run_serve")
    @patch("netbox_sync.cli.load_dotenv")
    def test_main_serve_dispatches(self, mock_dotenv, mock_run_serve):
        main(["serve"])

        mock_run_serve.assert_called_once()
        args = mock_run_serve.call_args[0][0]
        assert args.command == "serve"
        assert args.host == "127.0.0.1"
        assert args.port == 8000

    @patch("netbox_sync.cli._run_serve")
    @patch("netbox_sync.cli.load_dotenv")
    def test_main_serve_custom_args(self, mock_dotenv, mock_run_serve):
        main(["serve", "--host", "127.0.0.1", "--port", "9000"])

        args = mock_run_serve.call_args[0][0]
        assert args.host == "127.0.0.1"
        assert args.port == 9000

    def test_run_serve_starts_uvicorn(self):
        from netbox_sync.cli import _run_serve

        mock_config = MagicMock()
        mock_config.zabbix_configured = False
        mock_config.vcd_configured = False

        args = parse_args(["serve", "--host", "localhost", "--port", "3000"])

        mock_uvicorn_mod = MagicMock()
        mock_app = MagicMock()

        with patch("netbox_sync.cli.Config") as cfg_cls, \
             patch("netbox_sync.clients.yandex.YandexCloudClient"), \
             patch("netbox_sync.clients.netbox.NetBoxClient"):
            cfg_cls.from_env.return_value = mock_config

            with patch.dict("sys.modules", {"uvicorn": mock_uvicorn_mod}), \
                 patch("netbox_sync.web.app.create_app", return_value=mock_app):
                _run_serve(args)

            mock_uvicorn_mod.run.assert_called_once_with(
                mock_app, host="localhost", port=3000
            )

    @patch("netbox_sync.cli.load_dotenv")
    def test_run_serve_config_error_exits(self, mock_dotenv):
        from netbox_sync.cli import _run_serve

        args = parse_args(["serve"])

        with patch("netbox_sync.cli.Config") as cfg_cls:
            cfg_cls.from_env.side_effect = ValueError("Missing NETBOX_URL")
            with pytest.raises(SystemExit) as exc_info:
                _run_serve(args)
            assert exc_info.value.code == 1


class TestCLIIntegration:
    """Integration tests using subprocess."""

    def test_version_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "netbox_sync", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert f"netbox-sync {netbox_sync.__version__}" in result.stdout

    def test_help_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "netbox_sync", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--version" in result.stdout
        assert "serve" in result.stdout
        assert "sync" in result.stdout

    def test_serve_help_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "netbox_sync", "serve", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--host" in result.stdout
        assert "--port" in result.stdout

    def test_sync_help_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "netbox_sync", "sync", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--dry-run" in result.stdout
        assert "--no-cleanup" in result.stdout
        assert "--standard" in result.stdout
