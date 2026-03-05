"""Tests for the FastAPI web application."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netbox_sync.config import Config
from netbox_sync.web.app import create_app


class TestCreateApp:
    """Tests for the application factory."""

    def test_create_app_returns_fastapi_instance(self):
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_create_app_with_config(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
        )
        app = create_app(config=config)
        assert app.state.config is config

    def test_create_app_without_config(self):
        app = create_app()
        assert app.state.config is None

    def test_app_title(self):
        app = create_app()
        assert app.title == "NetBox Sync"


class TestDashboardRoute:
    """Tests for the GET / dashboard route."""

    def test_dashboard_returns_200(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200

    def test_dashboard_returns_html(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]

    def test_dashboard_contains_title(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/")
        assert "NetBox Sync Dashboard" in response.text

    def test_dashboard_shows_yandex_cloud_configured(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/")
        assert "Yandex Cloud" in response.text
        assert "Configured" in response.text

    def test_dashboard_shows_vcd_not_configured(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/")
        assert "vCloud Director" in response.text
        assert "Not configured" in response.text

    def test_dashboard_shows_vcd_configured(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
            vcd_url="https://vcd.example.com",
            vcd_user="admin",
            vcd_password="secret",
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/")
        assert "vCloud Director" in response.text
        # Both "Configured" spans should exist (YC and vCD)
        assert response.text.count("Configured") >= 2

    def test_dashboard_shows_zabbix_not_configured(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/")
        assert "Zabbix" in response.text

    def test_dashboard_shows_all_providers_configured(self):
        config = Config(
            yc_token="test-token",
            netbox_url="https://netbox.example.com",
            netbox_token="nb-token",
            vcd_url="https://vcd.example.com",
            vcd_user="admin",
            vcd_password="secret",
            zabbix_url="https://zabbix.example.com",
            zabbix_user="admin",
            zabbix_password="secret",
        )
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/")
        assert "Active providers: 3" in response.text

    def test_dashboard_without_config_returns_200(self):
        app = create_app()
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200

    def test_dashboard_renders_base_template(self):
        app = create_app()
        client = TestClient(app)
        response = client.get("/")
        assert "<!DOCTYPE html>" in response.text
        assert "htmx" in response.text

    def test_dashboard_has_navigation(self):
        app = create_app()
        client = TestClient(app)
        response = client.get("/")
        assert 'href="/"' in response.text
        assert 'href="/comparison"' in response.text
