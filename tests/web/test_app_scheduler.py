"""Tests for scheduler integration with FastAPI app."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from infraverse.config import Config
from infraverse.web.app import create_app


def _make_config(**overrides):
    defaults = dict(
        yc_token="tok",
        netbox_url="https://nb.example.com",
        netbox_token="nbt",
        sync_interval_minutes=0,
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestAppSchedulerDisabled:
    def test_no_scheduler_when_interval_zero(self):
        app = create_app("sqlite:///:memory:", config=_make_config(sync_interval_minutes=0))
        assert app.state.scheduler is None

    def test_no_scheduler_when_config_none(self):
        app = create_app("sqlite:///:memory:", config=None)
        assert app.state.scheduler is None

    def test_no_scheduler_when_no_config_arg(self):
        app = create_app("sqlite:///:memory:")
        assert app.state.scheduler is None

    def test_app_works_without_scheduler(self):
        app = create_app("sqlite:///:memory:")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200


class TestAppSchedulerEnabled:
    @patch("infraverse.scheduler.SchedulerService")
    def test_creates_scheduler_when_interval_positive(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=30)
        app = create_app("sqlite:///:memory:", config=config)
        assert app.state.scheduler is mock_instance

    @patch("infraverse.scheduler.SchedulerService")
    def test_scheduler_starts_on_lifespan_enter(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=15)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app):
            mock_instance.start.assert_called_once_with(15)

    @patch("infraverse.scheduler.SchedulerService")
    def test_scheduler_stops_on_lifespan_exit(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=10)
        app = create_app("sqlite:///:memory:", config=config)

        client = TestClient(app)
        client.__enter__()
        mock_instance.start.assert_called_once()
        mock_instance.stop.assert_not_called()

        client.__exit__(None, None, None)
        mock_instance.stop.assert_called_once()

    def test_scheduler_not_created_when_interval_zero_but_config_present(self):
        config = _make_config(sync_interval_minutes=0)
        app = create_app("sqlite:///:memory:", config=config)
        assert app.state.scheduler is None

    @patch("infraverse.scheduler.SchedulerService")
    def test_scheduler_stored_in_app_state(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=5)
        app = create_app("sqlite:///:memory:", config=config)
        assert app.state.scheduler is mock_instance

    @patch("infraverse.scheduler.SchedulerService")
    def test_custom_interval_passed_to_start(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=60)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app):
            mock_instance.start.assert_called_once_with(60)
