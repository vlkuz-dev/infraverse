"""Tests for sync trigger and status routes."""

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


# --- POST /sync/trigger ---


class TestTriggerNoScheduler:
    """Tests for POST /sync/trigger when scheduler is not configured."""

    def test_returns_503_json(self):
        app = create_app("sqlite:///:memory:")
        client = TestClient(app)
        resp = client.post("/sync/trigger")
        assert resp.status_code == 503
        assert "Scheduler not configured" in resp.json()["error"]

    def test_returns_html_for_htmx(self):
        app = create_app("sqlite:///:memory:")
        client = TestClient(app)
        resp = client.post("/sync/trigger", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert "Scheduler not configured" in resp.text
        assert "text/html" in resp.headers["content-type"]

    def test_no_scheduler_with_zero_interval_config(self):
        config = _make_config(sync_interval_minutes=0)
        app = create_app("sqlite:///:memory:", config=config)
        client = TestClient(app)
        resp = client.post("/sync/trigger")
        assert resp.status_code == 503


class TestTriggerWithScheduler:
    """Tests for POST /sync/trigger when scheduler is configured."""

    @patch("infraverse.scheduler.SchedulerService")
    def test_calls_trigger_now(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = {
            "running": True,
            "next_run_time": "2026-03-06T12:00:00+00:00",
            "last_run_time": None,
            "last_result": None,
        }
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=5)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app) as client:
            resp = client.post("/sync/trigger")
            assert resp.status_code == 200
            mock_instance.trigger_now.assert_called_once()

    @patch("infraverse.scheduler.SchedulerService")
    def test_returns_status_json(self, mock_sched_cls):
        mock_instance = MagicMock()
        expected_status = {
            "running": True,
            "next_run_time": "2026-03-06T12:00:00+00:00",
            "last_run_time": None,
            "last_result": None,
        }
        mock_instance.get_status.return_value = expected_status
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=5)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app) as client:
            resp = client.post("/sync/trigger")
            assert resp.json() == expected_status

    @patch("infraverse.scheduler.SchedulerService")
    def test_returns_html_for_htmx(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = {
            "running": True,
            "next_run_time": "2026-03-06T12:00:00+00:00",
            "last_run_time": None,
            "last_result": None,
        }
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=5)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app) as client:
            resp = client.post("/sync/trigger", headers={"HX-Request": "true"})
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert "Scheduler running" in resp.text

    @patch("infraverse.scheduler.SchedulerService")
    def test_trigger_after_error_shows_error(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = {
            "running": True,
            "next_run_time": "2026-03-06T12:00:00+00:00",
            "last_run_time": "2026-03-06T11:00:00+00:00",
            "last_result": {"error": "Connection refused"},
        }
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=5)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app) as client:
            resp = client.post("/sync/trigger", headers={"HX-Request": "true"})
            assert "Connection refused" in resp.text


# --- GET /sync/status ---


class TestStatusNoScheduler:
    """Tests for GET /sync/status when scheduler is not configured."""

    def test_returns_inactive_status_json(self):
        app = create_app("sqlite:///:memory:")
        client = TestClient(app)
        resp = client.get("/sync/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["next_run_time"] is None
        assert data["last_run_time"] is None
        assert data["last_result"] is None

    def test_returns_html_for_htmx(self):
        app = create_app("sqlite:///:memory:")
        client = TestClient(app)
        resp = client.get("/sync/status", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Scheduler not active" in resp.text


class TestStatusWithScheduler:
    """Tests for GET /sync/status when scheduler is configured."""

    @patch("infraverse.scheduler.SchedulerService")
    def test_returns_scheduler_status(self, mock_sched_cls):
        mock_instance = MagicMock()
        expected_status = {
            "running": True,
            "next_run_time": "2026-03-06T12:30:00+00:00",
            "last_run_time": "2026-03-06T12:00:00+00:00",
            "last_result": {"vms_found": 10},
        }
        mock_instance.get_status.return_value = expected_status
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=30)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app) as client:
            resp = client.get("/sync/status")
            assert resp.status_code == 200
            assert resp.json() == expected_status

    @patch("infraverse.scheduler.SchedulerService")
    def test_returns_html_with_all_fields(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = {
            "running": True,
            "next_run_time": "2026-03-06T12:30:00+00:00",
            "last_run_time": "2026-03-06T12:00:00+00:00",
            "last_result": {"vms_found": 10},
        }
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=30)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app) as client:
            resp = client.get("/sync/status", headers={"HX-Request": "true"})
            assert "Scheduler running" in resp.text
            assert "Next run:" in resp.text
            assert "Last run:" in resp.text
            assert "Last sync successful" in resp.text

    @patch("infraverse.scheduler.SchedulerService")
    def test_html_shows_error_result(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = {
            "running": True,
            "next_run_time": "2026-03-06T12:30:00+00:00",
            "last_run_time": "2026-03-06T12:00:00+00:00",
            "last_result": {"error": "Timeout"},
        }
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=30)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app) as client:
            resp = client.get("/sync/status", headers={"HX-Request": "true"})
            assert "Error: Timeout" in resp.text
            assert "text-danger" in resp.text


class TestStatusResponseFormat:
    """Tests for /sync/status JSON response format compliance."""

    def test_json_has_required_keys(self):
        app = create_app("sqlite:///:memory:")
        client = TestClient(app)
        resp = client.get("/sync/status")
        data = resp.json()
        assert "running" in data
        assert "next_run_time" in data
        assert "last_run_time" in data
        assert "last_result" in data

    @patch("infraverse.scheduler.SchedulerService")
    def test_json_format_with_scheduler(self, mock_sched_cls):
        mock_instance = MagicMock()
        mock_instance.get_status.return_value = {
            "running": True,
            "next_run_time": "2026-03-06T12:30:00+00:00",
            "last_run_time": None,
            "last_result": None,
        }
        mock_sched_cls.return_value = mock_instance
        config = _make_config(sync_interval_minutes=30)
        app = create_app("sqlite:///:memory:", config=config)

        with TestClient(app) as client:
            resp = client.get("/sync/status")
            data = resp.json()
            assert isinstance(data["running"], bool)
            assert isinstance(data["next_run_time"], str)
            assert data["last_run_time"] is None
            assert data["last_result"] is None
