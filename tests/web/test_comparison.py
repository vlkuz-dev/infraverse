"""Tests for comparison route."""

import pytest
from fastapi.testclient import TestClient

from infraverse.web.app import create_app
from infraverse.db.repository import Repository


@pytest.fixture
def app():
    """Create a test app with in-memory SQLite database."""
    return create_app("sqlite:///:memory:")


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded_app():
    """Create a test app with VMs and monitoring hosts for comparison."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        tenant = repo.create_tenant("Acme Corp")

        yc_account = repo.create_cloud_account(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC Russia",
        )
        vc_account = repo.create_cloud_account(
            tenant_id=tenant.id,
            provider_type="vcloud",
            name="vCloud@Dataspace",
        )

        # VMs in both cloud and monitoring
        repo.upsert_vm(
            cloud_account_id=yc_account.id,
            external_id="vm-001",
            name="web-server-1",
            status="active",
            ip_addresses=["10.0.0.1"],
        )
        repo.upsert_vm(
            cloud_account_id=yc_account.id,
            external_id="vm-002",
            name="db-server-1",
            status="active",
            ip_addresses=["10.0.0.2"],
        )
        # VM only in cloud (no monitoring match)
        repo.upsert_vm(
            cloud_account_id=vc_account.id,
            external_id="vm-003",
            name="app-server-1",
            status="active",
            ip_addresses=["10.0.0.3"],
        )

        # Monitoring hosts
        repo.upsert_monitoring_host(
            source="zabbix",
            external_id="z-001",
            name="web-server-1",
            status="active",
            ip_addresses=["10.0.0.1"],
        )
        repo.upsert_monitoring_host(
            source="zabbix",
            external_id="z-002",
            name="db-server-1",
            status="active",
            ip_addresses=["10.0.0.2"],
        )
        # Monitoring host not in cloud
        repo.upsert_monitoring_host(
            source="zabbix",
            external_id="z-003",
            name="legacy-host-1",
            status="active",
            ip_addresses=["10.0.0.99"],
        )

        session.commit()
    return app


@pytest.fixture
def seeded_client(seeded_app):
    return TestClient(seeded_app)


# --- Empty state tests ---


def test_comparison_empty_state(client):
    resp = client.get("/comparison")
    assert resp.status_code == 200
    html = resp.text
    assert "Comparison" in html
    assert "No VMs found" in html


def test_comparison_empty_summary(client):
    resp = client.get("/comparison")
    html = resp.text
    assert "Total" in html
    assert "In Sync" in html
    assert "With Issues" in html


def test_comparison_extends_base_template(client):
    resp = client.get("/comparison")
    html = resp.text
    assert "<!doctype html>" in html.lower()
    assert "Infraverse" in html
    assert "tabler" in html


def test_comparison_active_page(client):
    resp = client.get("/comparison")
    html = resp.text
    # The comparison nav item should have active class
    import re
    match = re.search(
        r'<li class="nav-item\s+active">\s*<a class="nav-link" href="/comparison">',
        html,
    )
    assert match is not None, "Comparison nav-item should have active class"


# --- Seeded state tests ---


def test_comparison_shows_vms(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    assert "web-server-1" in html
    assert "db-server-1" in html
    assert "app-server-1" in html
    assert "legacy-host-1" in html


def test_comparison_shows_provider_badges(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    assert "yandex_cloud" in html
    assert "vcloud" in html


def test_comparison_shows_discrepancies(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    # app-server-1 is in cloud but not monitoring
    assert "in cloud but not in monitoring" in html
    # legacy-host-1 is in monitoring but not cloud
    assert "in monitoring but not in cloud" in html


def test_comparison_no_netbox_discrepancy_when_not_configured(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    # NetBox is not configured, so NetBox discrepancies are suppressed
    assert "not in NetBox" not in html


def test_comparison_summary_counts(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    # 4 total VMs (web-server-1, db-server-1, app-server-1, legacy-host-1)
    assert "4 results" in html


def test_comparison_table_headers(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    assert "VM Name" in html
    assert "Cloud" in html
    # NetBox column hidden when netbox_configured=False
    assert "<th>NetBox</th>" not in html
    assert "Monitoring" in html
    assert "Provider" in html
    assert "Discrepancies" in html


# --- Filter tests ---


def test_filter_by_provider_yandex(seeded_client):
    resp = seeded_client.get("/comparison?provider=yandex_cloud")
    html = resp.text
    assert "web-server-1" in html
    assert "db-server-1" in html
    # app-server-1 is vcloud, should be filtered out
    assert "app-server-1" not in html
    # legacy-host-1 has no cloud_provider, should be filtered out
    assert "legacy-host-1" not in html


def test_filter_by_provider_vcloud(seeded_client):
    resp = seeded_client.get("/comparison?provider=vcloud")
    html = resp.text
    assert "app-server-1" in html
    assert "web-server-1" not in html


def test_filter_by_status_in_sync_shows_matched_vms(seeded_client):
    resp = seeded_client.get("/comparison?status=in_sync")
    html = resp.text
    # web-server-1 and db-server-1 are in both cloud and monitoring, no discrepancies
    assert "web-server-1" in html
    assert "db-server-1" in html
    # app-server-1 and legacy-host-1 have discrepancies
    assert "app-server-1" not in html
    assert "legacy-host-1" not in html


def test_filter_by_status_with_issues(seeded_client):
    resp = seeded_client.get("/comparison?status=with_issues")
    html = resp.text
    # Only VMs with cloud/monitoring discrepancies
    assert "app-server-1" in html
    assert "legacy-host-1" in html
    # web-server-1 and db-server-1 are in sync (cloud + monitoring)
    assert "web-server-1" not in html
    assert "db-server-1" not in html


def test_filter_by_search(seeded_client):
    resp = seeded_client.get("/comparison?search=web")
    html = resp.text
    assert "web-server-1" in html
    assert "db-server-1" not in html
    assert "app-server-1" not in html


def test_filter_by_search_case_insensitive(seeded_client):
    resp = seeded_client.get("/comparison?search=WEB")
    html = resp.text
    assert "web-server-1" in html


def test_filter_combined_provider_and_status(seeded_client):
    resp = seeded_client.get("/comparison?provider=yandex_cloud&status=with_issues")
    html = resp.text
    # web-server-1 and db-server-1 are in sync (cloud + monitoring), no NetBox issues
    assert "web-server-1" not in html
    assert "db-server-1" not in html
    assert "app-server-1" not in html


def test_filter_combined_provider_and_search(seeded_client):
    resp = seeded_client.get("/comparison?provider=yandex_cloud&search=db")
    html = resp.text
    assert "db-server-1" in html
    assert "web-server-1" not in html


def test_filter_no_results(seeded_client):
    resp = seeded_client.get("/comparison?search=nonexistent")
    html = resp.text
    assert "No VMs found" in html
    assert "0 results" in html


# --- HTMX partial tests ---


def test_comparison_table_partial_endpoint(seeded_client):
    resp = seeded_client.get("/comparison/table")
    assert resp.status_code == 200
    html = resp.text
    # Partial should not include base template
    assert "<!doctype html>" not in html.lower()
    # But should include VM data
    assert "web-server-1" in html


def test_comparison_table_partial_with_filter(seeded_client):
    resp = seeded_client.get("/comparison/table?provider=vcloud")
    html = resp.text
    assert "app-server-1" in html
    assert "web-server-1" not in html


def test_comparison_table_partial_empty(client):
    resp = client.get("/comparison/table")
    assert resp.status_code == 200
    assert "No VMs found" in resp.text


# --- Provider dropdown tests ---


def test_comparison_provider_dropdown(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    assert "All providers" in html
    assert '<option value="vcloud"' in html
    assert '<option value="yandex_cloud"' in html


def test_comparison_provider_selected_state(seeded_client):
    resp = seeded_client.get("/comparison?provider=vcloud")
    html = resp.text
    assert 'value="vcloud" selected' in html


def test_comparison_status_selected_state(seeded_client):
    resp = seeded_client.get("/comparison?status=with_issues")
    html = resp.text
    assert 'value="with_issues" selected' in html


def test_comparison_search_preserves_value(seeded_client):
    resp = seeded_client.get("/comparison?search=test-query")
    html = resp.text
    assert 'value="test-query"' in html


# --- Quick-filter button tests ---


def test_quick_filter_buttons_present(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    assert 'id="quick-filter-buttons"' in html
    assert ">All</button>" in html
    assert ">With Issues</button>" in html
    assert ">In Sync</button>" in html


def test_quick_filter_all_button_active_by_default(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    # "All" button should have btn-primary (active) when no status filter
    assert 'data-status=""\n' in html or ('data-status=""' in html and "btn-primary" in html)
    import re
    match = re.search(
        r'class="btn btn-primary"[^>]*data-status=""',
        html,
    )
    assert match is not None, "All button should be active (btn-primary) by default"


def test_quick_filter_with_issues_button_active(seeded_client):
    resp = seeded_client.get("/comparison?status=with_issues")
    html = resp.text
    import re
    match = re.search(
        r'class="btn btn-primary"[^>]*data-status="with_issues"',
        html,
    )
    assert match is not None, "With Issues button should be active when status=with_issues"
    # All button should be outline
    match_all = re.search(
        r'class="btn btn-outline-primary"[^>]*data-status=""',
        html,
    )
    assert match_all is not None, "All button should be outline when status=with_issues"


def test_quick_filter_in_sync_button_active(seeded_client):
    resp = seeded_client.get("/comparison?status=in_sync")
    html = resp.text
    import re
    match = re.search(
        r'class="btn btn-primary"[^>]*data-status="in_sync"',
        html,
    )
    assert match is not None, "In Sync button should be active when status=in_sync"


def test_quick_filter_buttons_have_htmx_attrs(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    assert 'hx-get="/comparison/table"' in html
    assert 'hx-target="#comparison-table"' in html
    assert 'hx-include="[name=provider],[name=search]"' in html


# --- Table partial route with status filter tests ---


def test_table_partial_filter_status_in_sync(seeded_client):
    resp = seeded_client.get("/comparison/table?status=in_sync")
    assert resp.status_code == 200
    html = resp.text
    assert "web-server-1" in html
    assert "db-server-1" in html
    assert "app-server-1" not in html
    assert "legacy-host-1" not in html


def test_table_partial_filter_status_with_issues(seeded_client):
    resp = seeded_client.get("/comparison/table?status=with_issues")
    assert resp.status_code == 200
    html = resp.text
    assert "app-server-1" in html
    assert "legacy-host-1" in html
    assert "web-server-1" not in html
    assert "db-server-1" not in html


def test_table_partial_filter_status_all(seeded_client):
    resp = seeded_client.get("/comparison/table?status=")
    assert resp.status_code == 200
    html = resp.text
    assert "web-server-1" in html
    assert "db-server-1" in html
    assert "app-server-1" in html
    assert "legacy-host-1" in html


# --- Combined filter tests on table partial ---


def test_table_partial_combined_status_and_provider(seeded_client):
    resp = seeded_client.get("/comparison/table?status=with_issues&provider=vcloud")
    assert resp.status_code == 200
    html = resp.text
    # app-server-1 is vcloud with discrepancy (cloud but not monitoring)
    assert "app-server-1" in html
    # legacy-host-1 has no cloud provider, filtered by provider=vcloud
    assert "legacy-host-1" not in html
    assert "web-server-1" not in html


def test_table_partial_combined_status_and_search(seeded_client):
    resp = seeded_client.get("/comparison/table?status=in_sync&search=web")
    assert resp.status_code == 200
    html = resp.text
    assert "web-server-1" in html
    assert "db-server-1" not in html


def test_table_partial_combined_all_three_filters(seeded_client):
    resp = seeded_client.get(
        "/comparison/table?status=in_sync&provider=yandex_cloud&search=db"
    )
    assert resp.status_code == 200
    html = resp.text
    assert "db-server-1" in html
    assert "web-server-1" not in html
    assert "app-server-1" not in html
    assert "legacy-host-1" not in html


def test_table_partial_combined_filters_no_results(seeded_client):
    resp = seeded_client.get(
        "/comparison/table?status=with_issues&provider=yandex_cloud&search=nonexistent"
    )
    assert resp.status_code == 200
    html = resp.text
    assert "No VMs found" in html
    assert "0 results" in html
