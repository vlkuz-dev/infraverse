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

        # Monitoring hosts (linked to cloud accounts)
        repo.upsert_monitoring_host(
            source="zabbix",
            external_id="z-001",
            name="web-server-1",
            status="active",
            ip_addresses=["10.0.0.1"],
            cloud_account_id=yc_account.id,
        )
        repo.upsert_monitoring_host(
            source="zabbix",
            external_id="z-002",
            name="db-server-1",
            status="active",
            ip_addresses=["10.0.0.2"],
            cloud_account_id=yc_account.id,
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


def test_comparison_monitoring_discrepancies_with_config():
    """When Zabbix is configured via config but has zero hosts, monitoring discrepancies still show."""
    from infraverse.config import Config

    config = Config(
        yc_token="t",
        netbox_url="https://netbox.example.com",
        netbox_token="t",
        zabbix_url="https://zabbix.example.com",
        zabbix_user="admin",
        zabbix_password="secret",
    )
    app = create_app("sqlite:///:memory:", config=config)
    with app.state.session_factory() as session:
        repo = Repository(session)
        tenant = repo.create_tenant("Test")
        account = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC")
        repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="vm-001",
            name="unmonitored-vm",
            status="active",
        )
        session.commit()

    client = TestClient(app)
    resp = client.get("/comparison")
    html = resp.text
    assert "in cloud but not in monitoring" in html


def test_comparison_no_netbox_discrepancy_when_not_configured(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    # NetBox is not configured, so NetBox discrepancies are suppressed
    assert "not in NetBox" not in html


def test_comparison_summary_counts(seeded_client):
    resp = seeded_client.get("/comparison")
    html = resp.text
    # 3 total VMs (web-server-1, db-server-1, app-server-1)
    assert "3 results" in html


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
    # app-server-1 is in cloud but not monitoring
    assert "app-server-1" in html
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
    assert "web-server-1" not in html
    assert "db-server-1" not in html


def test_table_partial_filter_status_all(seeded_client):
    resp = seeded_client.get("/comparison/table?status=")
    assert resp.status_code == 200
    html = resp.text
    assert "web-server-1" in html
    assert "db-server-1" in html
    assert "app-server-1" in html


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


# --- Tenant-scoped comparison tests ---


def _create_multi_tenant_comparison_app():
    """Create app with two tenants, VMs, and monitoring data for comparison."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t1 = repo.create_tenant("Acme Corp")
        t2 = repo.create_tenant("Beta Inc")

        a1 = repo.create_cloud_account(t1.id, "yandex_cloud", "Acme YC")
        a2 = repo.create_cloud_account(t2.id, "vcloud", "Beta vCloud")

        # Acme VMs
        repo.upsert_vm(a1.id, "vm-001", "acme-web", status="active", ip_addresses=["10.0.0.1"])
        repo.upsert_vm(a1.id, "vm-002", "acme-db", status="active", ip_addresses=["10.0.0.2"])

        # Beta VMs
        repo.upsert_vm(a2.id, "vm-010", "beta-app", status="active", ip_addresses=["10.1.0.1"])

        # Monitoring: only acme-web is monitored (linked to its cloud account)
        repo.upsert_monitoring_host("zabbix", "z-001", "acme-web", status="active", ip_addresses=["10.0.0.1"], cloud_account_id=a1.id)
        # Monitoring: beta-app is monitored (linked to its cloud account)
        repo.upsert_monitoring_host("zabbix", "z-010", "beta-app", status="active", ip_addresses=["10.1.0.1"], cloud_account_id=a2.id)

        session.commit()
        ids = {"t1": t1.id, "t2": t2.id, "a1": a1.id, "a2": a2.id}
    return app, ids


def test_comparison_with_tenant_filter_shows_only_tenant_vms():
    """Comparison scoped to tenant only shows that tenant's VMs."""
    app, ids = _create_multi_tenant_comparison_app()
    client = TestClient(app)
    resp = client.get(f"/comparison?tenant_id={ids['t1']}")
    html = resp.text
    assert resp.status_code == 200
    assert "acme-web" in html
    assert "acme-db" in html
    assert "beta-app" not in html


def test_comparison_with_tenant_filter_second_tenant():
    """Comparison scoped to second tenant shows only its VMs."""
    app, ids = _create_multi_tenant_comparison_app()
    client = TestClient(app)
    resp = client.get(f"/comparison?tenant_id={ids['t2']}")
    html = resp.text
    assert "beta-app" in html
    assert "acme-web" not in html
    assert "acme-db" not in html


def test_comparison_without_tenant_filter_shows_all():
    """Comparison without tenant filter shows all cloud VMs."""
    app, ids = _create_multi_tenant_comparison_app()
    client = TestClient(app)
    resp = client.get("/comparison")
    html = resp.text
    assert "acme-web" in html
    assert "acme-db" in html
    assert "beta-app" in html


def test_comparison_tenant_filter_invalid_shows_all():
    """Invalid tenant_id falls back to showing all VMs."""
    app, ids = _create_multi_tenant_comparison_app()
    client = TestClient(app)
    resp = client.get("/comparison?tenant_id=9999")
    html = resp.text
    assert "acme-web" in html
    assert "beta-app" in html


def test_comparison_tenant_filter_discrepancies():
    """Tenant-scoped comparison correctly identifies discrepancies within tenant."""
    app, ids = _create_multi_tenant_comparison_app()
    client = TestClient(app)
    resp = client.get(f"/comparison?tenant_id={ids['t1']}")
    html = resp.text
    # acme-db has no monitoring -> discrepancy
    assert "in cloud but not in monitoring" in html


def test_comparison_table_partial_with_tenant():
    """HTMX table partial respects tenant_id filter."""
    app, ids = _create_multi_tenant_comparison_app()
    client = TestClient(app)
    resp = client.get(f"/comparison/table?tenant_id={ids['t1']}")
    html = resp.text
    assert resp.status_code == 200
    assert "acme-web" in html
    assert "beta-app" not in html


def test_comparison_tenant_filter_combined_with_provider():
    """Tenant filter works with provider filter."""
    app, ids = _create_multi_tenant_comparison_app()
    client = TestClient(app)
    resp = client.get(f"/comparison?tenant_id={ids['t1']}&provider=yandex_cloud")
    html = resp.text
    assert "acme-web" in html
    assert "acme-db" in html
    assert "beta-app" not in html


def test_comparison_has_tenant_selector():
    """Comparison page shows tenant selector when tenants exist."""
    app, ids = _create_multi_tenant_comparison_app()
    client = TestClient(app)
    resp = client.get("/comparison")
    html = resp.text
    assert "All Tenants" in html
    assert "Acme Corp" in html
    assert "Beta Inc" in html


# --- Partial monitoring data tests ---


def _create_partial_monitoring_app():
    """Create app where one account has monitoring data and another doesn't."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t1 = repo.create_tenant("Corp A")
        t2 = repo.create_tenant("Corp B")

        a1 = repo.create_cloud_account(t1.id, "yandex_cloud", "Corp A YC")
        a2 = repo.create_cloud_account(t2.id, "yandex_cloud", "Corp B YC")

        # Corp A VMs: both monitored
        repo.upsert_vm(a1.id, "vm-001", "a-web", status="active")
        repo.upsert_vm(a1.id, "vm-002", "a-db", status="active")
        repo.upsert_monitoring_host(
            "zabbix", "z-001", "a-web", status="active",
            cloud_account_id=a1.id,
        )
        repo.upsert_monitoring_host(
            "zabbix", "z-002", "a-db", status="active",
            cloud_account_id=a1.id,
        )

        # Corp B VMs: none monitored
        repo.upsert_vm(a2.id, "vm-010", "b-web", status="active")
        repo.upsert_vm(a2.id, "vm-011", "b-api", status="active")

        session.commit()
        ids = {"t1": t1.id, "t2": t2.id, "a1": a1.id, "a2": a2.id}
    return app, ids


def test_partial_monitoring_tenant_with_monitoring_all_in_sync():
    """Tenant whose VMs are all monitored shows no discrepancies."""
    app, ids = _create_partial_monitoring_app()
    client = TestClient(app)
    resp = client.get(f"/comparison?tenant_id={ids['t1']}")
    html = resp.text
    assert "a-web" in html
    assert "a-db" in html
    assert "in cloud but not in monitoring" not in html


def test_partial_monitoring_tenant_without_monitoring_shows_discrepancies():
    """Tenant whose VMs have no monitoring shows discrepancies for all."""
    app, ids = _create_partial_monitoring_app()
    client = TestClient(app)
    resp = client.get(f"/comparison?tenant_id={ids['t2']}")
    html = resp.text
    assert "b-web" in html
    assert "b-api" in html
    # No monitoring hosts linked to this tenant, so all VMs should have discrepancies
    assert "in cloud but not in monitoring" in html


def test_partial_monitoring_global_shows_mixed():
    """Global comparison shows both monitored and unmonitored VMs."""
    app, ids = _create_partial_monitoring_app()
    client = TestClient(app)
    resp = client.get("/comparison")
    html = resp.text
    assert "a-web" in html
    assert "a-db" in html
    assert "b-web" in html
    assert "b-api" in html


def test_partial_monitoring_global_in_sync_filter():
    """Global filter for in_sync returns only monitored VMs."""
    app, ids = _create_partial_monitoring_app()
    client = TestClient(app)
    resp = client.get("/comparison?status=in_sync")
    html = resp.text
    assert "a-web" in html
    assert "a-db" in html
    assert "b-web" not in html
    assert "b-api" not in html


def test_partial_monitoring_global_with_issues_filter():
    """Global filter for with_issues returns only unmonitored VMs."""
    app, ids = _create_partial_monitoring_app()
    client = TestClient(app)
    resp = client.get("/comparison?status=with_issues")
    html = resp.text
    assert "b-web" in html
    assert "b-api" in html
    assert "a-web" not in html
    assert "a-db" not in html


# --- NetBox comparison tests ---


def _create_netbox_comparison_app():
    """Create app with cloud VMs and NetBox hosts for comparison."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        tenant = repo.create_tenant("Acme Corp")
        account = repo.create_cloud_account(tenant.id, "yandex_cloud", "YC")

        # Cloud VMs
        repo.upsert_vm(account.id, "vm-001", "web-01", status="active", ip_addresses=["10.0.0.1"])
        repo.upsert_vm(account.id, "vm-002", "db-01", status="active", ip_addresses=["10.0.0.2"])
        repo.upsert_vm(account.id, "vm-003", "app-01", status="active", ip_addresses=["10.0.0.3"])

        # NetBox hosts: web-01 and db-01 exist, app-01 does not; orphan-nb only in NetBox
        repo.upsert_netbox_host(external_id="nb-1", name="web-01", status="active", ip_addresses=["10.0.0.1"])
        repo.upsert_netbox_host(external_id="nb-2", name="db-01", status="active", ip_addresses=["10.0.0.2"])
        repo.upsert_netbox_host(external_id="nb-4", name="orphan-nb", status="active", ip_addresses=["10.0.0.99"])

        session.commit()
    return app


def test_netbox_column_shown_when_netbox_hosts_exist():
    """When NetBox hosts exist in DB, the NetBox column appears."""
    app = _create_netbox_comparison_app()
    client = TestClient(app)
    resp = client.get("/comparison")
    html = resp.text
    assert "<th>NetBox</th>" in html


def test_netbox_column_hidden_when_no_netbox_hosts(client):
    """When no NetBox hosts exist, the NetBox column is hidden."""
    resp = client.get("/comparison")
    html = resp.text
    assert "<th>NetBox</th>" not in html


def test_missing_from_netbox_card_shown():
    """Missing from NetBox summary card appears when NetBox hosts exist."""
    app = _create_netbox_comparison_app()
    client = TestClient(app)
    resp = client.get("/comparison")
    html = resp.text
    assert "Missing from NetBox" in html
    assert "Missing from Cloud" in html


def test_missing_from_netbox_card_hidden_without_netbox(client):
    """Missing from NetBox card does not appear when no NetBox hosts."""
    resp = client.get("/comparison")
    html = resp.text
    assert "Missing from NetBox" not in html
    assert "Missing from Cloud" not in html


def test_vm_in_cloud_not_in_netbox_discrepancy():
    """VM in cloud but not in NetBox shows discrepancy."""
    app = _create_netbox_comparison_app()
    client = TestClient(app)
    resp = client.get("/comparison")
    html = resp.text
    assert "in cloud but not in NetBox" in html


def test_vm_in_netbox_not_in_cloud_discrepancy():
    """VM in NetBox but not in cloud shows discrepancy."""
    app = _create_netbox_comparison_app()
    client = TestClient(app)
    resp = client.get("/comparison")
    html = resp.text
    assert "in NetBox but not in cloud" in html


def test_netbox_comparison_htmx_partial():
    """HTMX table partial includes NetBox column when NetBox hosts exist."""
    app = _create_netbox_comparison_app()
    client = TestClient(app)
    resp = client.get("/comparison/table")
    html = resp.text
    assert "<th>NetBox</th>" in html
    assert "web-01" in html
