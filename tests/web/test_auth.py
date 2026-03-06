"""Tests for OIDC auth routes."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from starlette.responses import RedirectResponse

from authlib.integrations.base_client import OAuthError

from infraverse.config_file import InfraverseConfig, OidcConfig
from infraverse.web.app import create_app


@pytest.fixture
def oidc_config():
    return OidcConfig(
        provider_url="https://idp.example.com/realms/test",
        client_id="infraverse",
        client_secret="test-secret-key-for-sessions",
        required_role="infraverse-admin",
    )


@pytest.fixture
def infraverse_config(oidc_config):
    return InfraverseConfig(oidc=oidc_config)


@pytest.fixture
def app(infraverse_config):
    return create_app("sqlite:///:memory:", infraverse_config=infraverse_config)


@pytest.fixture
def client(app):
    return TestClient(app)


def _mock_oauth(app, authorize_redirect_rv=None, authorize_access_token_rv=None,
                authorize_access_token_exc=None):
    """Replace app.state.oauth.oidc with a mock that returns given values."""
    mock_oidc = MagicMock()
    if authorize_redirect_rv is not None:
        mock_oidc.authorize_redirect = AsyncMock(return_value=authorize_redirect_rv)
    if authorize_access_token_rv is not None:
        mock_oidc.authorize_access_token = AsyncMock(
            return_value=authorize_access_token_rv,
        )
    if authorize_access_token_exc is not None:
        mock_oidc.authorize_access_token = AsyncMock(
            side_effect=authorize_access_token_exc,
        )
    app.state.oauth.oidc = mock_oidc
    return mock_oidc


class TestLogin:
    """Tests for /auth/login redirect."""

    def test_login_redirects_to_oidc_provider(self, app, client):
        authorize_url = "https://idp.example.com/realms/test/protocol/openid-connect/auth?client_id=infraverse"
        _mock_oauth(app, authorize_redirect_rv=RedirectResponse(authorize_url))

        resp = client.get("/auth/login", follow_redirects=False)
        assert resp.status_code == 307
        assert "idp.example.com" in resp.headers["location"]

    def test_login_passes_callback_redirect_uri(self, app, client):
        _mock_oauth(
            app,
            authorize_redirect_rv=RedirectResponse("https://idp.example.com/auth"),
        )

        client.get("/auth/login", follow_redirects=False)

        mock_oidc = app.state.oauth.oidc
        args = mock_oidc.authorize_redirect.call_args
        # Second positional arg is the redirect_uri
        redirect_uri = str(args[0][1])
        assert "/auth/callback" in redirect_uri


class TestCallback:
    """Tests for /auth/callback route."""

    def test_valid_token_with_role_redirects_to_dashboard(self, app, client):
        _mock_oauth(app, authorize_access_token_rv={
            "userinfo": {
                "sub": "user-123",
                "name": "John Doe",
                "email": "john@example.com",
                "roles": ["infraverse-admin"],
            },
        })

        resp = client.get("/auth/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_valid_token_without_required_role_returns_403(self, app, client):
        _mock_oauth(app, authorize_access_token_rv={
            "userinfo": {
                "sub": "user-456",
                "name": "Jane Smith",
                "email": "jane@example.com",
                "roles": ["viewer"],
            },
        })

        resp = client.get("/auth/callback")
        assert resp.status_code == 403
        assert "insufficient permissions" in resp.text.lower()

    def test_valid_token_no_roles_returns_403(self, app, client):
        _mock_oauth(app, authorize_access_token_rv={
            "userinfo": {
                "sub": "user-789",
                "name": "No Role User",
                "email": "norole@example.com",
            },
        })

        resp = client.get("/auth/callback")
        assert resp.status_code == 403

    def test_invalid_token_returns_401(self, app, client):
        _mock_oauth(
            app,
            authorize_access_token_exc=OAuthError(error="invalid_token"),
        )

        resp = client.get("/auth/callback")
        assert resp.status_code == 401
        assert "authentication failed" in resp.text.lower()

    def test_keycloak_realm_access_roles(self, app, client):
        """Roles extracted from Keycloak realm_access.roles claim."""
        _mock_oauth(app, authorize_access_token_rv={
            "userinfo": {
                "sub": "user-kc",
                "name": "KC User",
                "email": "kc@example.com",
                "realm_access": {"roles": ["infraverse-admin"]},
            },
        })

        resp = client.get("/auth/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"


class TestLogout:
    """Tests for /auth/logout route."""

    def test_logout_redirects_to_login(self, app, client):
        resp = client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/auth/login"

    def test_logout_clears_session(self, app, client):
        """After login+logout, session user data is cleared."""
        # Step 1: Simulate login via callback
        _mock_oauth(app, authorize_access_token_rv={
            "userinfo": {
                "sub": "user-123",
                "name": "John Doe",
                "email": "john@example.com",
                "roles": ["infraverse-admin"],
            },
        })
        client.get("/auth/callback", follow_redirects=False)

        # Verify authenticated user can access dashboard
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 200

        # Step 2: Logout
        client.get("/auth/logout", follow_redirects=False)

        # Verify session is cleared: accessing protected route redirects to login
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["location"]
