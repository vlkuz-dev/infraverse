"""Tests for VM list page with tenant/account filtering."""

import pytest
from fastapi.testclient import TestClient

from infraverse.web.app import create_app
from infraverse.db.repository import Repository


@pytest.fixture
def app():
    return create_app("sqlite:///:memory:")


@pytest.fixture
def client(app):
    return TestClient(app)


def _create_multi_tenant_app():
    """Create app with two tenants, each having accounts and VMs."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t1 = repo.create_tenant("Acme Corp")
        t2 = repo.create_tenant("Beta Inc")

        a1 = repo.create_cloud_account(t1.id, "yandex_cloud", "Acme YC")
        a2 = repo.create_cloud_account(t1.id, "vcloud", "Acme vCloud")
        a3 = repo.create_cloud_account(t2.id, "yandex_cloud", "Beta YC")

        repo.upsert_vm(a1.id, "vm-001", "acme-web-1", status="active", ip_addresses=["10.0.0.1"])
        repo.upsert_vm(a1.id, "vm-002", "acme-db-1", status="offline", ip_addresses=["10.0.0.2"])
        repo.upsert_vm(a2.id, "vm-003", "acme-app-1", status="active", ip_addresses=["10.0.0.3"])
        repo.upsert_vm(a3.id, "vm-010", "beta-api-1", status="active", ip_addresses=["10.0.1.1"])
        repo.upsert_vm(a3.id, "vm-011", "beta-api-2", status="active", ip_addresses=["10.0.1.2"])

        session.commit()

        # Return IDs for test assertions
        ids = {
            "t1": t1.id, "t2": t2.id,
            "a1": a1.id, "a2": a2.id, "a3": a3.id,
        }
    return app, ids


# --- Empty state tests ---


def test_vm_list_empty_state(client):
    resp = client.get("/vms")
    assert resp.status_code == 200
    assert "No VMs found" in resp.text


def test_vm_list_extends_base_template(client):
    resp = client.get("/vms")
    html = resp.text
    assert "<!doctype html>" in html.lower()
    assert "Infraverse" in html


# --- VM list with data ---


def test_vm_list_shows_all_vms():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms")
    html = resp.text
    assert resp.status_code == 200
    assert "acme-web-1" in html
    assert "acme-db-1" in html
    assert "acme-app-1" in html
    assert "beta-api-1" in html
    assert "beta-api-2" in html


def test_vm_list_shows_vm_count():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms")
    assert "5 VM" in resp.text


def test_vm_list_shows_status_badges():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms")
    html = resp.text
    assert "bg-success-lt" in html  # active
    assert "bg-danger-lt" in html   # offline


def test_vm_list_shows_account_names():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms")
    html = resp.text
    assert "Acme YC" in html
    assert "Beta YC" in html


def test_vm_list_has_links_to_detail():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms")
    html = resp.text
    assert "/vms/" in html


# --- Tenant filtering ---


def test_vm_list_filter_by_tenant():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get(f"/vms?tenant_id={ids['t1']}")
    html = resp.text
    assert resp.status_code == 200
    assert "acme-web-1" in html
    assert "acme-db-1" in html
    assert "acme-app-1" in html
    assert "beta-api-1" not in html
    assert "beta-api-2" not in html


def test_vm_list_filter_by_second_tenant():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get(f"/vms?tenant_id={ids['t2']}")
    html = resp.text
    assert "beta-api-1" in html
    assert "beta-api-2" in html
    assert "acme-web-1" not in html


def test_vm_list_filter_by_tenant_shows_correct_count():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get(f"/vms?tenant_id={ids['t1']}")
    assert "3 VM" in resp.text


def test_vm_list_filter_invalid_tenant_shows_all():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms?tenant_id=9999")
    html = resp.text
    assert resp.status_code == 200
    assert "acme-web-1" in html
    assert "beta-api-1" in html


# --- Account filtering ---


def test_vm_list_filter_by_account():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get(f"/vms?account_id={ids['a1']}")
    html = resp.text
    assert resp.status_code == 200
    assert "acme-web-1" in html
    assert "acme-db-1" in html
    assert "acme-app-1" not in html
    assert "beta-api-1" not in html


def test_vm_list_filter_by_account_shows_correct_count():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get(f"/vms?account_id={ids['a1']}")
    assert "2 VM" in resp.text


def test_vm_list_filter_invalid_account_shows_all():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms?account_id=9999")
    html = resp.text
    assert "acme-web-1" in html
    assert "beta-api-1" in html


# --- Tenant selector in template ---


def test_vm_list_has_tenant_selector():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms")
    html = resp.text
    assert "All Tenants" in html
    assert "Acme Corp" in html
    assert "Beta Inc" in html


def test_vm_list_tenant_selector_preserves_selection():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get(f"/vms?tenant_id={ids['t1']}")
    html = resp.text
    assert f'value="{ids["t1"]}" selected' in html


# --- Navigation ---


def test_vm_list_active_nav():
    app, ids = _create_multi_tenant_app()
    client = TestClient(app)
    resp = client.get("/vms")
    html = resp.text
    import re
    match = re.search(
        r'<li class="nav-item\s+active">\s*<a class="nav-link" href="/vms">',
        html,
    )
    assert match is not None, "VMs nav-item should have active class"
