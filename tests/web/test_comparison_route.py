"""Tests for the GET /comparison route."""

from fastapi.testclient import TestClient

from netbox_sync.clients.base import VMInfo
from netbox_sync.clients.zabbix import ZabbixHost
from netbox_sync.config import Config
from netbox_sync.web.app import create_app


def _make_config():
    return Config(
        yc_token="test-token",
        netbox_url="https://netbox.example.com",
        netbox_token="nb-token",
    )


def _make_cloud_vms():
    return [
        VMInfo(
            name="web-01",
            id="vm-1",
            status="active",
            ip_addresses=["10.0.0.1"],
            vcpus=2,
            memory_mb=4096,
            provider="yandex-cloud",
            cloud_name="my-cloud",
            folder_name="prod",
        ),
        VMInfo(
            name="db-01",
            id="vm-2",
            status="active",
            ip_addresses=["10.0.0.2"],
            vcpus=4,
            memory_mb=8192,
            provider="vcloud-director",
            cloud_name="my-vcd",
            folder_name="prod",
        ),
        VMInfo(
            name="app-01",
            id="vm-3",
            status="active",
            ip_addresses=["10.0.0.3"],
            vcpus=2,
            memory_mb=4096,
            provider="yandex-cloud",
            cloud_name="my-cloud",
            folder_name="staging",
        ),
    ]


def _make_netbox_vms():
    return [
        VMInfo(
            name="web-01",
            id="nb-1",
            status="active",
            ip_addresses=["10.0.0.1"],
            vcpus=2,
            memory_mb=4096,
            provider="netbox",
            cloud_name="",
            folder_name="",
        ),
        VMInfo(
            name="db-01",
            id="nb-2",
            status="active",
            ip_addresses=["10.0.0.2"],
            vcpus=4,
            memory_mb=8192,
            provider="netbox",
            cloud_name="",
            folder_name="",
        ),
    ]


def _make_zabbix_hosts():
    return [
        ZabbixHost(name="web-01", hostid="z-1", status="active", ip_addresses=["10.0.0.1"]),
        ZabbixHost(name="db-01", hostid="z-2", status="active", ip_addresses=["10.0.0.2"]),
        ZabbixHost(name="app-01", hostid="z-3", status="active", ip_addresses=["10.0.0.3"]),
    ]


class TestComparisonRoute:
    """Tests for the GET /comparison route."""

    def test_comparison_returns_200(self):
        app = create_app(config=_make_config())
        client = TestClient(app)
        response = client.get("/comparison")
        assert response.status_code == 200

    def test_comparison_returns_html(self):
        app = create_app(config=_make_config())
        client = TestClient(app)
        response = client.get("/comparison")
        assert "text/html" in response.headers["content-type"]

    def test_comparison_renders_vm_names(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison")
        assert "web-01" in response.text
        assert "db-01" in response.text
        assert "app-01" in response.text

    def test_comparison_shows_status_columns(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison")
        assert "Cloud" in response.text
        assert "NetBox" in response.text
        assert "Zabbix" in response.text

    def test_comparison_shows_discrepancies(self):
        """app-01 is in cloud and zabbix but not in netbox."""
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison")
        assert "in cloud but not in NetBox" in response.text

    def test_comparison_shows_summary(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison")
        assert "Total: 3" in response.text

    def test_comparison_empty_data(self):
        app = create_app(config=_make_config())
        client = TestClient(app)
        response = client.get("/comparison")
        assert response.status_code == 200
        assert "No VMs found" in response.text

    def test_comparison_has_refresh_button(self):
        app = create_app(config=_make_config())
        client = TestClient(app)
        response = client.get("/comparison")
        assert "Refresh" in response.text
        assert "hx-get" in response.text

    def test_comparison_has_filter_form(self):
        app = create_app(config=_make_config())
        client = TestClient(app)
        response = client.get("/comparison")
        assert 'name="provider"' in response.text
        assert 'name="status"' in response.text
        assert 'name="search"' in response.text


class TestComparisonFiltering:
    """Tests for comparison route filtering parameters."""

    def test_filter_by_provider(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison?provider=yandex-cloud")
        assert "web-01" in response.text
        assert "app-01" in response.text
        # db-01 is vcloud-director, should be filtered out
        assert "db-01" not in response.text

    def test_filter_by_provider_vcloud(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison?provider=vcloud-director")
        assert "db-01" in response.text
        assert "web-01" not in response.text

    def test_filter_discrepancies_only(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison?status=discrepancies")
        # app-01 has discrepancy (in cloud, not in netbox)
        assert "app-01" in response.text
        # web-01 is in all three — no discrepancy
        assert "web-01" not in response.text

    def test_filter_by_name_search(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison?search=web")
        assert "web-01" in response.text
        assert "db-01" not in response.text
        assert "app-01" not in response.text

    def test_filter_by_name_search_case_insensitive(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison?search=WEB")
        assert "web-01" in response.text

    def test_filter_combined_provider_and_status(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison?provider=yandex-cloud&status=discrepancies")
        # app-01 is yandex-cloud with discrepancy
        assert "app-01" in response.text
        # web-01 is yandex-cloud but no discrepancy
        assert "web-01" not in response.text

    def test_filter_no_match_shows_empty(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison?search=nonexistent")
        assert "No VMs found" in response.text


class TestComparisonHTMX:
    """Tests for HTMX partial rendering."""

    def test_htmx_request_returns_partial(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison", headers={"HX-Request": "true"})
        assert response.status_code == 200
        # Partial should have table but NOT full page layout
        assert "<table" in response.text
        assert "<!DOCTYPE html>" not in response.text

    def test_non_htmx_request_returns_full_page(self):
        app = create_app(
            config=_make_config(),
            cloud_fetcher=_make_cloud_vms,
            netbox_fetcher=_make_netbox_vms,
            zabbix_fetcher=_make_zabbix_hosts,
        )
        client = TestClient(app)
        response = client.get("/comparison")
        assert "<!DOCTYPE html>" in response.text
        assert "<table" in response.text
