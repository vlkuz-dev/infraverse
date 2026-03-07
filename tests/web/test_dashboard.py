"""Tests for dashboard route."""

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
    """Create a test app with seed data in the database."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        tenant = repo.create_tenant("Acme Corp", description="Test tenant")
        account = repo.create_cloud_account(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC Russia",
        )
        repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="vm-001",
            name="web-server-1",
            status="active",
            ip_addresses=["10.0.0.1"],
            vcpus=2,
            memory_mb=4096,
        )
        repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="vm-002",
            name="db-server-1",
            status="offline",
            ip_addresses=["10.0.0.2"],
            vcpus=4,
            memory_mb=8192,
        )
        run = repo.create_sync_run(source="yandex_cloud", cloud_account_id=account.id)
        repo.update_sync_run(
            sync_run_id=run.id,
            status="success",
            items_found=2,
            items_created=2,
        )
        session.commit()
    return app


@pytest.fixture
def seeded_client(seeded_app):
    return TestClient(seeded_app)


# --- Empty state tests ---


def test_dashboard_empty_state(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "Dashboard" in html
    assert "Total VMs" in html
    assert "No providers configured" in html
    assert "No tenants configured" in html
    assert "No sync runs yet" in html


def test_dashboard_empty_shows_zero_counts(client):
    resp = client.get("/")
    html = resp.text
    # Summary cards should show 0
    assert ">0<" in html.replace(" ", "").replace("\n", "")


# --- Seeded state tests ---


def test_dashboard_shows_vm_counts(seeded_client):
    resp = seeded_client.get("/")
    html = resp.text
    assert "Total VMs" in html
    assert ">2<" in html.replace(" ", "").replace("\n", "")
    assert "Active VMs" in html
    assert "Offline VMs" in html


def test_dashboard_shows_tenant(seeded_client):
    resp = seeded_client.get("/")
    html = resp.text
    assert "Acme Corp" in html
    assert "Test tenant" in html


def test_dashboard_shows_provider_summary(seeded_client):
    resp = seeded_client.get("/")
    html = resp.text
    assert "yandex_cloud" in html


def test_dashboard_shows_sync_run(seeded_client):
    resp = seeded_client.get("/")
    html = resp.text
    # Verify sync run data is rendered (source + status badge)
    assert "yandex_cloud" in html
    assert "bg-success-lt" in html


def test_dashboard_active_page(seeded_client):
    import re
    resp = seeded_client.get("/")
    html = resp.text
    # Sidebar should mark the dashboard nav item specifically as active
    pattern = r'<li class="nav-item active">\s*<a class="nav-link" href="/">'
    assert re.search(pattern, html), "Dashboard nav item should be active"


def test_dashboard_extends_base_template(seeded_client):
    resp = seeded_client.get("/")
    html = resp.text
    assert "<!doctype html>" in html.lower()
    assert "Infraverse" in html
    assert "tabler" in html


def test_dashboard_multiple_providers():
    """Test with multiple provider types."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Multi Corp")
        repo.create_cloud_account(t.id, "yandex_cloud", "YC Russia")
        repo.create_cloud_account(t.id, "vcloud", "vCloud@Dataspace")
        repo.create_cloud_account(t.id, "yandex_cloud", "YC Kazakhstan")
        session.commit()

    client = TestClient(app)
    resp = client.get("/")
    html = resp.text
    assert "yandex_cloud" in html
    assert "vcloud" in html


def test_dashboard_multiple_tenants():
    """Test with multiple tenants."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        repo.create_tenant("Tenant A")
        repo.create_tenant("Tenant B")
        session.commit()

    client = TestClient(app)
    resp = client.get("/")
    html = resp.text
    assert "Tenant A" in html
    assert "Tenant B" in html


def test_dashboard_sync_run_statuses():
    """Test different sync run status badges."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Test")
        a = repo.create_cloud_account(t.id, "yandex_cloud", "YC")

        run1 = repo.create_sync_run(source="yandex_cloud", cloud_account_id=a.id)
        repo.update_sync_run(run1.id, status="success", items_found=5)

        run2 = repo.create_sync_run(source="vcloud", cloud_account_id=a.id)
        repo.update_sync_run(run2.id, status="failed", error_message="Connection refused")

        session.commit()

    client = TestClient(app)
    resp = client.get("/")
    html = resp.text
    assert "bg-success-lt" in html
    assert "bg-danger-lt" in html
    assert "Connection refused" in html


# --- Tenant filter tests ---


def _create_multi_tenant_app():
    """Create app with two tenants, each with accounts and VMs."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t1 = repo.create_tenant("Acme Corp", description="Acme")
        t2 = repo.create_tenant("Beta Inc", description="Beta")
        a1 = repo.create_cloud_account(t1.id, "yandex_cloud", "Acme YC")
        a2 = repo.create_cloud_account(t2.id, "vcloud", "Beta vCloud")
        repo.upsert_vm(a1.id, "vm-001", "acme-web-1", status="active")
        repo.upsert_vm(a1.id, "vm-002", "acme-db-1", status="offline")
        repo.upsert_vm(a2.id, "vm-010", "beta-app-1", status="active")
        session.commit()
    return app


def test_dashboard_no_filter_shows_all():
    """Without tenant_id param, dashboard shows all VMs."""
    app = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/")
    html = resp.text
    assert resp.status_code == 200
    assert "Acme Corp" in html
    assert "Beta Inc" in html


def test_dashboard_filter_by_tenant_id():
    """With tenant_id param, dashboard shows only that tenant's data."""
    app = _create_multi_tenant_app()
    with app.state.session_factory() as session:
        repo = Repository(session)
        acme = repo.get_tenant_by_name("Acme Corp")
        acme_id = acme.id
    client = TestClient(app)
    resp = client.get(f"/?tenant_id={acme_id}")
    html = resp.text
    assert resp.status_code == 200
    # Should show Acme's VMs (2 total: 1 active, 1 offline)
    assert "acme-web-1" not in html  # VMs aren't listed on dashboard, but counts should match
    # Total VMs count should be 2 for Acme tenant
    compact = html.replace(" ", "").replace("\n", "")
    assert ">2<" in compact  # 2 total VMs
    # Should show only Acme's provider
    assert "yandex_cloud" in html
    # Should not show Beta's provider in the filtered view
    assert "Beta vCloud" not in html


def test_dashboard_filter_shows_only_filtered_tenant_accounts():
    """Filtered dashboard only shows the selected tenant's accounts."""
    app = _create_multi_tenant_app()
    with app.state.session_factory() as session:
        repo = Repository(session)
        beta = repo.get_tenant_by_name("Beta Inc")
        beta_id = beta.id
    client = TestClient(app)
    resp = client.get(f"/?tenant_id={beta_id}")
    html = resp.text
    assert "Beta vCloud" in html
    assert "Acme YC" not in html


def test_dashboard_filter_invalid_tenant_id_shows_all():
    """Invalid/non-existent tenant_id falls back to showing all data."""
    app = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/?tenant_id=9999")
    assert resp.status_code == 200
    html = resp.text
    assert "Acme Corp" in html
    assert "Beta Inc" in html


def test_dashboard_has_tenant_selector():
    """Dashboard should show a tenant selector dropdown when tenants exist."""
    app = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/")
    html = resp.text
    assert "tenant_id" in html
    assert "All Tenants" in html
    assert "Acme Corp" in html
    assert "Beta Inc" in html


def test_dashboard_tenant_selector_preserves_selection():
    """Tenant selector should show the selected tenant as active."""
    app = _create_multi_tenant_app()
    with app.state.session_factory() as session:
        repo = Repository(session)
        acme = repo.get_tenant_by_name("Acme Corp")
        acme_id = acme.id
    client = TestClient(app)
    resp = client.get(f"/?tenant_id={acme_id}")
    html = resp.text
    # The selected option should be marked
    assert f'value="{acme_id}"' in html


def test_dashboard_stat_cards_no_links(seeded_client):
    """Stat cards should not navigate away from dashboard."""
    resp = seeded_client.get("/")
    html = resp.text
    # Should NOT have old <a href="/vms"> wrappers
    assert '<a href="/vms' not in html


def test_dashboard_has_fetch_now_card(seeded_client):
    """Dashboard should have a Fetch Now card styled as a stat card."""
    resp = seeded_client.get("/")
    html = resp.text
    assert "Fetch Now" in html
    assert 'hx-post="/sync/trigger"' in html
    assert "card-stat-purple" in html


def test_dashboard_has_collapsible_vm_section(seeded_client):
    """Dashboard should have a collapsible VM table section."""
    resp = seeded_client.get("/")
    html = resp.text
    assert "vm-table-collapse" in html
    assert "Virtual Machines" in html
    assert 'data-bs-toggle="collapse"' in html


# --- VM table partial endpoint tests ---


def test_dashboard_vm_table_returns_all_vms(seeded_client):
    """GET /dashboard/vm-table returns VM table partial with all VMs."""
    resp = seeded_client.get("/dashboard/vm-table")
    assert resp.status_code == 200
    html = resp.text
    assert "All VMs" in html
    assert "web-server-1" in html
    assert "db-server-1" in html
    assert "(2)" in html


def test_dashboard_vm_table_filter_active(seeded_client):
    """GET /dashboard/vm-table?status=active returns only active VMs."""
    resp = seeded_client.get("/dashboard/vm-table?status=active")
    assert resp.status_code == 200
    html = resp.text
    assert "Active VMs" in html
    assert "web-server-1" in html
    assert "db-server-1" not in html
    assert "(1)" in html


def test_dashboard_vm_table_filter_offline(seeded_client):
    """GET /dashboard/vm-table?status=offline returns only offline VMs."""
    resp = seeded_client.get("/dashboard/vm-table?status=offline")
    assert resp.status_code == 200
    html = resp.text
    assert "Offline VMs" in html
    assert "db-server-1" in html
    assert "web-server-1" not in html
    assert "(1)" in html


def test_dashboard_vm_table_tenant_scoping():
    """GET /dashboard/vm-table?tenant_id=X returns only that tenant's VMs."""
    app = _create_multi_tenant_app()
    with app.state.session_factory() as session:
        repo = Repository(session)
        acme = repo.get_tenant_by_name("Acme Corp")
        acme_id = acme.id
    client = TestClient(app)
    resp = client.get(f"/dashboard/vm-table?tenant_id={acme_id}")
    assert resp.status_code == 200
    html = resp.text
    assert "acme-web-1" in html
    assert "acme-db-1" in html
    assert "beta-app-1" not in html


def test_dashboard_vm_table_invalid_status(seeded_client):
    """Invalid status is ignored and returns all VMs."""
    resp = seeded_client.get("/dashboard/vm-table?status=bogus")
    assert resp.status_code == 200
    html = resp.text
    assert "All VMs" in html
    assert "web-server-1" in html
    assert "db-server-1" in html


def test_dashboard_vm_table_empty(client):
    """VM table with no VMs shows empty message."""
    resp = client.get("/dashboard/vm-table")
    assert resp.status_code == 200
    html = resp.text
    assert "No VMs found" in html
    assert "(0)" in html
