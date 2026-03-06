"""Tests for cloud account detail page."""

from fastapi.testclient import TestClient

from infraverse.db.repository import Repository
from infraverse.web.app import create_app


def _create_seeded_app():
    """Create a test app with a cloud account, VMs, and sync runs."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        tenant = repo.create_tenant("Acme Corp", description="Test tenant")
        account = repo.create_cloud_account(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC Production",
            config={"folder_id": "abc123", "cloud_id": "xyz789"},
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
        repo.update_sync_run(run.id, status="success", items_found=2, items_created=2)
        session.commit()
        account_id = account.id
    return app, account_id


# --- Valid account tests ---


def test_account_detail_returns_200():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert resp.status_code == 200


def test_account_detail_shows_account_name():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert "YC Production" in resp.text


def test_account_detail_shows_provider_type():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert "yandex_cloud" in resp.text
    assert "bg-azure-lt" in resp.text


def test_account_detail_shows_tenant_name():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert "Acme Corp" in resp.text


def test_account_detail_shows_vm_count_and_status():
    import re
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    html = resp.text
    assert "Total VMs" in html
    assert "Active VMs" in html
    assert "Offline VMs" in html
    # Verify actual count values (2 VMs: 1 active, 1 offline)
    assert re.search(r"Total VMs</div>\s*<div[^>]*>2</div>", html), "Total VM count should be 2"
    assert re.search(r"Active VMs</div>\s*<div[^>]*>1</div>", html), "Active VM count should be 1"
    assert re.search(r"Offline VMs</div>\s*<div[^>]*>1</div>", html), "Offline VM count should be 1"


def test_account_detail_shows_vm_list():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    html = resp.text
    assert "web-server-1" in html
    assert "db-server-1" in html


def test_account_detail_vm_names_link_to_detail():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert "/vms/" in resp.text


def test_account_detail_shows_vm_status_badges():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    html = resp.text
    assert "bg-success-lt" in html  # active VM
    assert "bg-danger-lt" in html  # offline VM


def test_account_detail_shows_sync_runs():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    html = resp.text
    assert "Recent Sync Runs" in html
    assert "success" in html


def test_account_detail_shows_config():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    html = resp.text
    assert "Configuration" in html
    assert "folder_id" in html
    assert "abc123" in html


def test_account_detail_shows_timestamps():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert "UTC" in resp.text


def test_account_detail_extends_base_template():
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    html = resp.text
    assert "<!doctype html>" in html.lower()
    assert "Infraverse" in html
    assert "tabler" in html


def test_account_detail_empty_config():
    """Account with empty config should not show config card."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Test")
        a = repo.create_cloud_account(t.id, "vcloud", "vCloud Prod")
        session.commit()
        account_id = a.id

    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert resp.status_code == 200
    assert "vCloud Prod" in resp.text
    assert "Configuration" not in resp.text


def test_account_detail_no_vms():
    """Account with no VMs shows empty message."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Test")
        a = repo.create_cloud_account(t.id, "yandex_cloud", "Empty Account")
        session.commit()
        account_id = a.id

    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert resp.status_code == 200
    assert "No VMs found" in resp.text


def test_account_detail_no_sync_runs():
    """Account with no sync runs shows empty message."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Test")
        a = repo.create_cloud_account(t.id, "yandex_cloud", "Fresh Account")
        session.commit()
        account_id = a.id

    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert resp.status_code == 200
    assert "No sync runs yet" in resp.text


# --- Non-existent account tests ---


def test_account_detail_not_found_returns_404():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/accounts/99999")
    assert resp.status_code == 404


def test_account_detail_not_found_shows_message():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/accounts/99999")
    assert "Cloud account not found" in resp.text


def test_account_detail_not_found_has_dashboard_link():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/accounts/99999")
    assert 'href="/"' in resp.text


# --- External links tests ---


def test_account_detail_shows_external_links_when_configured():
    """Account detail shows external link buttons for YC accounts with folder_id."""
    from infraverse.config import Config

    config = Config(
        yc_token="t",
        netbox_url="https://netbox.example.com",
        netbox_token="t",
        yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
    )
    app = create_app("sqlite:///:memory:", config=config)
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Test")
        a = repo.create_cloud_account(
            t.id, "yandex_cloud", "YC Prod",
            config={"folder_id": "folder-xyz"},
        )
        session.commit()
        account_id = a.id

    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert resp.status_code == 200
    assert "External Links" in resp.text
    assert "Cloud Console" in resp.text
    assert "console.yandex.cloud/folders/folder-xyz" in resp.text


def test_account_detail_no_external_links_when_not_configured():
    """Account detail does not show external links when no URL templates."""
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert "External Links" not in resp.text


def test_account_detail_no_external_links_for_vcloud():
    """Account detail does not show YC console links for non-YC accounts."""
    from infraverse.config import Config

    config = Config(
        yc_token="t",
        netbox_url="https://netbox.example.com",
        netbox_token="t",
        yc_console_url="https://console.yandex.cloud/folders/{folder_id}/compute/instances/{vm_id}",
    )
    app = create_app("sqlite:///:memory:", config=config)
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Test")
        a = repo.create_cloud_account(t.id, "vcloud", "vCloud Prod")
        session.commit()
        account_id = a.id

    client = TestClient(app)
    resp = client.get(f"/accounts/{account_id}")
    assert resp.status_code == 200
    assert "External Links" not in resp.text


# --- Dashboard link tests ---


def test_dashboard_has_account_links():
    """Dashboard provider table should link to account detail pages."""
    app, account_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert f'/accounts/{account_id}' in resp.text
