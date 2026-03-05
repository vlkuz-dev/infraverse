"""Tests for FastAPI application factory."""

from fastapi.testclient import TestClient

from infraverse.web.app import create_app


def test_create_app_returns_fastapi_instance():
    app = create_app("sqlite:///:memory:")
    assert app.title == "Infraverse"


def test_create_app_has_session_factory():
    app = create_app("sqlite:///:memory:")
    assert app.state.session_factory is not None


def test_create_app_has_engine():
    app = create_app("sqlite:///:memory:")
    assert app.state.engine is not None


def test_app_serves_static_css():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_app_dashboard_route_exists():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200


def test_app_dashboard_returns_html():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/")
    assert "text/html" in resp.headers["content-type"]
