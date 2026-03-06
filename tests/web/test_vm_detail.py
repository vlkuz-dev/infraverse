"""Tests for VM detail page."""

from fastapi.testclient import TestClient

from infraverse.db.repository import Repository
from infraverse.web.app import create_app


def _create_seeded_app():
    """Create a test app with a VM in the database."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        tenant = repo.create_tenant("Acme Corp", description="Test tenant")
        account = repo.create_cloud_account(
            tenant_id=tenant.id,
            provider_type="yandex_cloud",
            name="YC Russia",
        )
        vm, _ = repo.upsert_vm(
            cloud_account_id=account.id,
            external_id="vm-001",
            name="web-server-1",
            status="active",
            ip_addresses=["10.0.0.1", "192.168.1.5"],
            vcpus=2,
            memory_mb=4096,
            cloud_name="my-cloud",
            folder_name="prod",
        )
        session.commit()
        vm_id = vm.id
    return app, vm_id


# --- Valid VM tests ---


def test_vm_detail_returns_200():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert resp.status_code == 200


def test_vm_detail_shows_vm_name():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "web-server-1" in resp.text


def test_vm_detail_shows_external_id():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "vm-001" in resp.text


def test_vm_detail_shows_status_badge():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "bg-success-lt" in resp.text
    assert "Active" in resp.text


def test_vm_detail_shows_ip_addresses():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "10.0.0.1" in resp.text
    assert "192.168.1.5" in resp.text


def test_vm_detail_shows_resources():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    html = resp.text
    import re
    assert re.search(r"vCPUs</div>\s*<div[^>]*>2</div>", html), "vcpus value should be 2"
    assert "4096 MB" in html  # memory


def test_vm_detail_shows_cloud_account():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "YC Russia" in resp.text
    assert "yandex_cloud" in resp.text


def test_vm_detail_shows_tenant():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "Acme Corp" in resp.text


def test_vm_detail_shows_cloud_and_folder():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "my-cloud" in resp.text
    assert "prod" in resp.text


def test_vm_detail_shows_timestamps():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "UTC" in resp.text


def test_vm_detail_extends_base_template():
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    html = resp.text
    assert "<!doctype html>" in html.lower()
    assert "Infraverse" in html
    assert "tabler" in html


def test_vm_detail_offline_status():
    """Test VM detail page with offline VM."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Test")
        a = repo.create_cloud_account(t.id, "vcloud", "vCloud")
        vm, _ = repo.upsert_vm(
            cloud_account_id=a.id,
            external_id="vm-offline",
            name="dead-server",
            status="offline",
        )
        session.commit()
        vm_id = vm.id

    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert resp.status_code == 200
    assert "bg-danger-lt" in resp.text
    assert "Offline" in resp.text


def test_vm_detail_no_resources():
    """Test VM detail page when vcpus/memory are None."""
    app = create_app("sqlite:///:memory:")
    with app.state.session_factory() as session:
        repo = Repository(session)
        t = repo.create_tenant("Test")
        a = repo.create_cloud_account(t.id, "yandex_cloud", "YC")
        vm, _ = repo.upsert_vm(
            cloud_account_id=a.id,
            external_id="vm-bare",
            name="minimal-vm",
            status="unknown",
        )
        session.commit()
        vm_id = vm.id

    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert resp.status_code == 200
    # The template should show "-" for missing resources
    assert "minimal-vm" in resp.text


# --- Non-existent VM tests ---


def test_vm_detail_not_found_returns_404():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/vms/99999")
    assert resp.status_code == 404


def test_vm_detail_not_found_shows_message():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/vms/99999")
    assert "VM not found" in resp.text


def test_vm_detail_not_found_has_dashboard_link():
    app = create_app("sqlite:///:memory:")
    client = TestClient(app)
    resp = client.get("/vms/99999")
    assert 'href="/"' in resp.text


# --- External links tests ---


def test_vm_detail_shows_external_links_when_configured():
    """VM detail shows external link buttons when config has URL templates."""
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
            t.id, "yandex_cloud", "YC",
            config={"folder_id": "folder-abc"},
        )
        vm, _ = repo.upsert_vm(
            cloud_account_id=a.id,
            external_id="vm-ext-001",
            name="linked-vm",
            status="active",
        )
        session.commit()
        vm_id = vm.id

    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert resp.status_code == 200
    assert "External Links" in resp.text
    assert "Cloud Console" in resp.text
    assert "console.yandex.cloud/folders/folder-abc/compute/instances/vm-ext-001" in resp.text


def test_vm_detail_no_external_links_when_not_configured():
    """VM detail does not show external links section when no URL templates configured."""
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get(f"/vms/{vm_id}")
    assert "External Links" not in resp.text


# --- Comparison table link tests ---


def test_comparison_table_has_vm_links():
    """Test that comparison table VM names link to detail pages."""
    app, vm_id = _create_seeded_app()
    client = TestClient(app)
    resp = client.get("/comparison")
    assert resp.status_code == 200
    assert f'/vms/{vm_id}' in resp.text
