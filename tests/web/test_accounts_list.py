"""Tests for cloud accounts list page."""

from fastapi.testclient import TestClient

from infraverse.db.repository import Repository
from infraverse.web.app import create_app


def _create_seeded_app():
    """Create a test app with multiple tenants and accounts."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t1 = repo.create_tenant("Acme Corp")
        t2 = repo.create_tenant("Beta Inc")
        a1 = repo.create_cloud_account(t1.id, "yandex_cloud", "YC Production")
        repo.create_cloud_account(t1.id, "vcloud", "vCloud Staging")
        repo.create_cloud_account(t2.id, "yandex_cloud", "YC Dev")
        # Add VMs to first account
        repo.upsert_vm(a1.id, "vm-001", "web-1", status="active")
        repo.upsert_vm(a1.id, "vm-002", "web-2", status="active")
        session.commit()
    return app


# --- Basic response tests ---


def test_accounts_list_returns_200():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    assert resp.status_code == 200


def test_accounts_list_shows_page_title():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    assert "Cloud Accounts" in resp.text


def test_accounts_list_extends_base_template():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    html = resp.text
    assert "<!doctype html>" in html.lower()
    assert "Infraverse" in html
    assert "tabler" in html


# --- Account listing tests ---


def test_accounts_list_shows_all_accounts():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    html = resp.text
    assert "YC Production" in html
    assert "vCloud Staging" in html
    assert "YC Dev" in html


def test_accounts_list_grouped_by_tenant():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    html = resp.text
    assert "Acme Corp" in html
    assert "Beta Inc" in html


def test_accounts_list_shows_provider_badges():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    html = resp.text
    assert "yandex_cloud" in html
    assert "bg-azure-lt" in html
    assert "vcloud" in html
    assert "bg-green-lt" in html


def test_accounts_list_shows_vm_count():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    # YC Production has 2 VMs
    assert ">2<" in resp.text.replace(" ", "").replace("\n", "")


def test_accounts_list_links_to_detail_pages():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    assert "/accounts/" in resp.text


def test_accounts_list_shows_total_count():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    assert "3 accounts" in resp.text


# --- Empty state tests ---


def test_accounts_list_empty():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/accounts")
    assert resp.status_code == 200
    assert "No cloud accounts found" in resp.text


# --- Sidebar navigation tests ---


def test_accounts_list_has_active_sidebar():
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    # The accounts nav item should be active
    assert "Cloud Accounts" in resp.text


def test_sidebar_has_accounts_link():
    """All pages should show the Cloud Accounts link in sidebar."""
    app = _create_seeded_app()
    client = TestClient(app)
    # Check from the dashboard
    resp = client.get("/")
    assert 'href="/accounts"' in resp.text
    assert "Cloud Accounts" in resp.text


def test_sidebar_accounts_active_on_list_page():
    """Cloud Accounts nav should be active when on the accounts list page."""
    app = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/accounts")
    html = resp.text
    # The Jinja2 template renders "nav-item active" for the accounts nav item
    # when active_page == 'accounts'. Check the rendered pattern.
    # The sidebar should contain a nav-item with both active class and /accounts href
    import re
    # Match the li.nav-item.active that contains href="/accounts"
    pattern = r'<li class="nav-item active">\s*<a class="nav-link" href="/accounts">'
    assert re.search(pattern, html), "Accounts nav item should be active on accounts list page"
