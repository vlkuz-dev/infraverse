"""Tests for pagination in web routes."""

from fastapi.testclient import TestClient

from infraverse.db.repository import Repository
from infraverse.web.app import create_app
from infraverse.web.pagination import DEFAULT_PER_PAGE, build_pagination, _page_range


# --- Unit tests for pagination helpers ---


class TestPageRange:
    def test_small_total(self):
        assert _page_range(1, 5) == [1, 2, 3, 4, 5]

    def test_seven_pages(self):
        assert _page_range(4, 7) == [1, 2, 3, 4, 5, 6, 7]

    def test_many_pages_at_start(self):
        result = _page_range(1, 20)
        assert result[0] == 1
        assert result[-1] == 20
        assert None in result

    def test_many_pages_at_middle(self):
        result = _page_range(10, 20)
        assert 1 in result
        assert 10 in result
        assert 20 in result
        assert None in result

    def test_many_pages_at_end(self):
        result = _page_range(20, 20)
        assert result[0] == 1
        assert result[-1] == 20


class TestBuildPagination:
    def test_single_page_returns_none(self):
        result = build_pagination(1, 50, 30, "/vms", {})
        assert result is None

    def test_two_pages(self):
        result = build_pagination(1, 50, 80, "/vms", {})
        assert result is not None
        assert result["page"] == 1
        assert result["total_pages"] == 2
        assert result["total_count"] == 80
        assert result["has_prev"] is False
        assert result["has_next"] is True
        assert result["showing_start"] == 1
        assert result["showing_end"] == 50

    def test_second_page(self):
        result = build_pagination(2, 50, 80, "/vms", {})
        assert result["page"] == 2
        assert result["has_prev"] is True
        assert result["has_next"] is False
        assert result["showing_start"] == 51
        assert result["showing_end"] == 80

    def test_page_clamped_to_max(self):
        result = build_pagination(99, 50, 80, "/vms", {})
        assert result["page"] == 2

    def test_urls_include_query_params(self):
        result = build_pagination(1, 50, 200, "/vms", {"tenant_id": 1, "status": "active"})
        url = result["page_urls"][2]
        assert "tenant_id=1" in url
        assert "status=active" in url
        assert "page=2" in url

    def test_urls_skip_none_params(self):
        result = build_pagination(1, 50, 200, "/vms", {"tenant_id": None, "status": ""})
        url = result["page_urls"][2]
        assert "tenant_id" not in url
        assert "status" not in url

    def test_per_page_in_url_when_non_default(self):
        result = build_pagination(1, 25, 200, "/vms", {})
        url = result["page_urls"][2]
        assert "per_page=25" in url

    def test_per_page_not_in_url_when_default(self):
        result = build_pagination(1, DEFAULT_PER_PAGE, 200, "/vms", {})
        url = result["page_urls"][2]
        assert "per_page" not in url

    def test_htmx_urls_present_when_configured(self):
        result = build_pagination(
            1, 50, 200, "/comparison", {},
            htmx_base_url="/comparison/table",
            htmx_target="#comparison-table",
        )
        assert result["htmx_urls"] is not None
        assert result["htmx_target"] == "#comparison-table"
        assert "/comparison/table?" in result["htmx_urls"][2]

    def test_htmx_urls_none_by_default(self):
        result = build_pagination(1, 50, 200, "/vms", {})
        assert result["htmx_urls"] is None

    def test_zero_total(self):
        result = build_pagination(1, 50, 0, "/vms", {})
        assert result is None


# --- Integration tests for /vms pagination ---


def _create_many_vms_app(count=120):
    """Create app with many VMs for pagination testing."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        tenant = repo.create_tenant("Test Corp")
        account = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Prod")
        for i in range(count):
            repo.upsert_vm(
                cloud_account_id=account.id,
                external_id=f"vm-{i:04d}",
                name=f"server-{i:04d}",
                status="active" if i % 2 == 0 else "offline",
                ip_addresses=[f"10.0.{i // 256}.{i % 256}"],
            )
        session.commit()
        ids = {"tenant": tenant.id, "account": account.id}
    return app, ids


class TestVmListPagination:
    def test_default_page_returns_first_page(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms")
        assert resp.status_code == 200
        assert "120 VM" in resp.text

    def test_page_1_shows_first_50_vms(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms?page=1")
        html = resp.text
        assert "server-0000" in html
        assert "server-0049" in html
        assert "server-0050" not in html

    def test_page_2_shows_next_50_vms(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms?page=2")
        html = resp.text
        assert "server-0050" in html
        assert "server-0099" in html
        assert "server-0000" not in html

    def test_page_3_shows_remaining_vms(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms?page=3")
        html = resp.text
        assert "server-0100" in html
        assert "server-0119" in html
        assert "server-0050" not in html

    def test_custom_per_page(self):
        app, ids = _create_many_vms_app(30)
        client = TestClient(app)
        resp = client.get("/vms?per_page=10&page=1")
        html = resp.text
        assert "server-0000" in html
        assert "server-0009" in html
        assert "server-0010" not in html

    def test_pagination_links_rendered(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms?page=1")
        html = resp.text
        assert "page-item" in html
        assert "page=2" in html

    def test_no_pagination_when_few_vms(self):
        app, ids = _create_many_vms_app(10)
        client = TestClient(app)
        resp = client.get("/vms")
        html = resp.text
        assert "page-item" not in html

    def test_pagination_preserves_tenant_filter(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get(f"/vms?tenant_id={ids['tenant']}&page=1")
        html = resp.text
        assert f"tenant_id={ids['tenant']}" in html
        assert "page=2" in html

    def test_pagination_preserves_status_filter(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms?status=active&page=1")
        html = resp.text
        assert "status=active" in html

    def test_vm_count_shows_total_not_page_count(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms?page=1")
        assert "120 VM" in resp.text

    def test_page_beyond_max_clamps_to_last(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms?page=999")
        assert resp.status_code == 200
        html = resp.text
        assert "server-0100" in html

    def test_showing_range_on_page_1(self):
        app, ids = _create_many_vms_app(120)
        client = TestClient(app)
        resp = client.get("/vms?page=1")
        html = resp.text
        assert "1\u201350" in html  # 1–50
        assert "of 120" in html


# --- Integration tests for /accounts/{id} pagination ---


class TestAccountDetailPagination:
    def test_default_shows_first_page(self):
        app, ids = _create_many_vms_app(80)
        client = TestClient(app)
        resp = client.get(f"/accounts/{ids['account']}")
        html = resp.text
        assert resp.status_code == 200
        assert "server-0000" in html
        assert "server-0049" in html

    def test_page_2(self):
        app, ids = _create_many_vms_app(80)
        client = TestClient(app)
        resp = client.get(f"/accounts/{ids['account']}?page=2")
        html = resp.text
        assert "server-0050" in html
        assert "server-0000" not in html

    def test_vm_counts_show_totals(self):
        """VM counts in sidebar should reflect ALL VMs, not just current page."""
        app, ids = _create_many_vms_app(80)
        client = TestClient(app)
        resp = client.get(f"/accounts/{ids['account']}?page=1")
        html = resp.text
        import re
        match = re.search(r"Total VMs</div>\s*<div[^>]*>(\d+)</div>", html)
        assert match is not None
        assert match.group(1) == "80"

    def test_no_pagination_with_few_vms(self):
        app, ids = _create_many_vms_app(10)
        client = TestClient(app)
        resp = client.get(f"/accounts/{ids['account']}")
        assert "page-item" not in resp.text

    def test_pagination_links_rendered(self):
        app, ids = _create_many_vms_app(80)
        client = TestClient(app)
        resp = client.get(f"/accounts/{ids['account']}")
        html = resp.text
        assert "page-item" in html
        assert "page=2" in html


# --- Integration tests for /comparison pagination ---


def _create_comparison_app(vm_count=150):
    """Create app with many VMs and monitoring hosts for comparison pagination."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        tenant = repo.create_tenant("Test Corp")
        account = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC Prod")
        for i in range(vm_count):
            repo.upsert_vm(
                cloud_account_id=account.id,
                external_id=f"vm-{i:04d}",
                name=f"server-{i:04d}",
                status="active",
                ip_addresses=[f"10.0.{i // 256}.{i % 256}"],
            )
            repo.upsert_monitoring_host(
                source="zabbix",
                external_id=f"z-{i:04d}",
                name=f"server-{i:04d}",
                status="active",
                ip_addresses=[f"10.0.{i // 256}.{i % 256}"],
                cloud_account_id=account.id,
            )
        session.commit()
    return app


class TestComparisonPagination:
    def test_default_page(self):
        app = _create_comparison_app(150)
        client = TestClient(app)
        resp = client.get("/comparison")
        assert resp.status_code == 200
        assert "150 results" in resp.text

    def test_page_1_shows_first_100(self):
        app = _create_comparison_app(150)
        client = TestClient(app)
        resp = client.get("/comparison?page=1")
        html = resp.text
        assert "server-0000" in html
        assert "server-0099" in html
        assert "server-0100" not in html

    def test_page_2_shows_remaining(self):
        app = _create_comparison_app(150)
        client = TestClient(app)
        resp = client.get("/comparison?page=2")
        html = resp.text
        assert "server-0100" in html
        assert "server-0149" in html
        assert "server-0000" not in html

    def test_summary_counts_reflect_full_data(self):
        """Summary cards should show totals for all VMs, not just the page."""
        app = _create_comparison_app(150)
        client = TestClient(app)
        resp = client.get("/comparison?page=1")
        html = resp.text
        # The "Total" summary card should show 150
        assert ">150<" in html

    def test_no_pagination_with_few_results(self):
        app = _create_comparison_app(50)
        client = TestClient(app)
        resp = client.get("/comparison")
        assert "page-item" not in resp.text

    def test_pagination_links_rendered(self):
        app = _create_comparison_app(150)
        client = TestClient(app)
        resp = client.get("/comparison?page=1")
        html = resp.text
        assert "page-item" in html
        assert "page=2" in html

    def test_htmx_attributes_on_pagination(self):
        """Comparison pagination links should have HTMX attributes."""
        app = _create_comparison_app(150)
        client = TestClient(app)
        resp = client.get("/comparison?page=1")
        html = resp.text
        assert "hx-get" in html
        assert "/comparison/table?" in html
        assert 'hx-target="#comparison-table"' in html

    def test_table_endpoint_pagination(self):
        app = _create_comparison_app(150)
        client = TestClient(app)
        resp = client.get("/comparison/table?page=2")
        html = resp.text
        assert resp.status_code == 200
        assert "server-0100" in html
        assert "server-0000" not in html

    def test_pagination_preserves_filters(self):
        app = _create_comparison_app(150)
        client = TestClient(app)
        # Use small per_page to guarantee pagination regardless of filter results
        resp = client.get("/comparison?status=in_sync&per_page=10&page=1")
        html = resp.text
        # With 150 in_sync VMs at per_page=10, there must be a page 2
        assert "page=2" in html
        assert "status=in_sync" in html

    def test_custom_per_page(self):
        app = _create_comparison_app(150)
        client = TestClient(app)
        resp = client.get("/comparison?per_page=50&page=1")
        html = resp.text
        assert "server-0000" in html
        assert "server-0049" in html
        assert "server-0050" not in html
