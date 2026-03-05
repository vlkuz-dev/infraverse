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
    assert "success" in html


def test_dashboard_active_page(seeded_client):
    resp = seeded_client.get("/")
    html = resp.text
    # Sidebar should mark dashboard as active
    assert 'nav-item active' in html


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
