"""Tests for optional auth mode and UI user display.

Verifies that:
- When OIDC is not configured, all routes are accessible without login
- When OIDC is configured, user info appears in the UI header
- When OIDC is not configured, no user info or login links appear
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from infraverse.config_file import InfraverseConfig, OidcConfig
from infraverse.web.app import create_app


# --- Fixtures for no-OIDC mode ---


@pytest.fixture
def app_no_oidc():
    """App with no OIDC configured (infraverse_config=None)."""
    return create_app("sqlite:///:memory:")


@pytest.fixture
def client_no_oidc(app_no_oidc):
    return TestClient(app_no_oidc)


@pytest.fixture
def app_no_oidc_with_config():
    """App with InfraverseConfig but no OIDC section."""
    cfg = InfraverseConfig(oidc=None)
    return create_app("sqlite:///:memory:", infraverse_config=cfg)


@pytest.fixture
def client_no_oidc_with_config(app_no_oidc_with_config):
    return TestClient(app_no_oidc_with_config)


# --- Fixtures for OIDC mode ---


@pytest.fixture
def oidc_config():
    return OidcConfig(
        provider_url="https://idp.example.com/realms/test",
        client_id="infraverse",
        client_secret="test-secret-key-for-sessions-xxxxx",
        required_role="infraverse-admin",
    )


@pytest.fixture
def app_with_oidc(oidc_config):
    cfg = InfraverseConfig(oidc=oidc_config)
    return create_app("sqlite:///:memory:", infraverse_config=cfg)


@pytest.fixture
def client_with_oidc(app_with_oidc):
    return TestClient(app_with_oidc)


def _login_user(app, client, name="Test User", email="test@example.com"):
    """Simulate OIDC login via callback mock."""
    mock_oidc = MagicMock()
    mock_oidc.authorize_access_token = AsyncMock(return_value={
        "userinfo": {
            "sub": "user-123",
            "name": name,
            "email": email,
            "roles": ["infraverse-admin"],
        },
    })
    app.state.oauth.oidc = mock_oidc
    client.get("/auth/callback", follow_redirects=False)


# --- Tests: No OIDC configured (infraverse_config=None) ---


class TestNoOidcAllRoutesAccessible:
    """When OIDC is not configured, all routes are accessible without login."""

    def test_dashboard_accessible_without_auth(self, client_no_oidc):
        resp = client_no_oidc.get("/")
        assert resp.status_code == 200

    def test_accounts_accessible_without_auth(self, client_no_oidc):
        resp = client_no_oidc.get("/accounts")
        assert resp.status_code == 200

    def test_vms_accessible_without_auth(self, client_no_oidc):
        resp = client_no_oidc.get("/vms")
        assert resp.status_code == 200

    def test_comparison_accessible_without_auth(self, client_no_oidc):
        resp = client_no_oidc.get("/comparison")
        assert resp.status_code == 200

    def test_health_accessible_without_auth(self, client_no_oidc):
        resp = client_no_oidc.get("/health")
        assert resp.status_code == 200

    def test_no_redirect_to_login(self, client_no_oidc):
        """Dashboard does NOT redirect to /auth/login."""
        resp = client_no_oidc.get("/", follow_redirects=False)
        assert resp.status_code == 200


class TestNoOidcWithConfigAllRoutesAccessible:
    """When InfraverseConfig exists but OIDC section is absent."""

    def test_dashboard_accessible(self, client_no_oidc_with_config):
        resp = client_no_oidc_with_config.get("/")
        assert resp.status_code == 200

    def test_accounts_accessible(self, client_no_oidc_with_config):
        resp = client_no_oidc_with_config.get("/accounts")
        assert resp.status_code == 200

    def test_comparison_accessible(self, client_no_oidc_with_config):
        resp = client_no_oidc_with_config.get("/comparison")
        assert resp.status_code == 200

    def test_no_auth_routes_registered(self, app_no_oidc_with_config):
        """Auth routes (/auth/login etc.) should not be registered."""
        route_paths = [r.path for r in app_no_oidc_with_config.routes if hasattr(r, "path")]
        assert "/auth/login" not in route_paths
        assert "/auth/callback" not in route_paths
        assert "/auth/logout" not in route_paths


# --- Tests: UI user display ---


class TestUiUserDisplayNoOidc:
    """Without OIDC, no user info or logout link should appear."""

    def test_no_user_info_in_header(self, client_no_oidc):
        resp = client_no_oidc.get("/")
        assert "Logout" not in resp.text

    def test_no_login_link_in_header(self, client_no_oidc):
        resp = client_no_oidc.get("/")
        assert "/auth/login" not in resp.text


class TestUiUserDisplayWithOidc:
    """With OIDC, authenticated user info should appear in the header."""

    def test_authenticated_user_name_in_header(self, app_with_oidc, client_with_oidc):
        _login_user(app_with_oidc, client_with_oidc, name="Alice Admin")
        resp = client_with_oidc.get("/")
        assert "Alice Admin" in resp.text

    def test_authenticated_user_email_in_header(self, app_with_oidc, client_with_oidc):
        _login_user(app_with_oidc, client_with_oidc, email="alice@example.com")
        resp = client_with_oidc.get("/")
        assert "alice@example.com" in resp.text

    def test_logout_link_present_when_authenticated(self, app_with_oidc, client_with_oidc):
        _login_user(app_with_oidc, client_with_oidc)
        resp = client_with_oidc.get("/")
        assert "/auth/logout" in resp.text
