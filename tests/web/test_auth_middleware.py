"""Tests for auth middleware: session checking, redirect, expiry, role check."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from infraverse.config_file import InfraverseConfig, OidcConfig
from infraverse.web.app import create_app


@pytest.fixture
def oidc_config():
    return OidcConfig(
        provider_url="https://idp.example.com/realms/test",
        client_id="infraverse",
        client_secret="test-secret-key-for-sessions-xxxxx",
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


def _mock_oauth(app, authorize_redirect_rv=None, authorize_access_token_rv=None):
    """Replace app.state.oauth.oidc with a mock."""
    mock_oidc = MagicMock()
    if authorize_redirect_rv is not None:
        mock_oidc.authorize_redirect = AsyncMock(return_value=authorize_redirect_rv)
    if authorize_access_token_rv is not None:
        mock_oidc.authorize_access_token = AsyncMock(
            return_value=authorize_access_token_rv,
        )
    app.state.oauth.oidc = mock_oidc
    return mock_oidc


def _login_user(app, client, roles=None):
    """Simulate OIDC login by calling the callback route with mocked token."""
    if roles is None:
        roles = ["infraverse-admin"]
    _mock_oauth(app, authorize_access_token_rv={
        "userinfo": {
            "sub": "user-123",
            "name": "Test User",
            "email": "test@example.com",
            "roles": roles,
        },
    })
    client.get("/auth/callback", follow_redirects=False)


class TestAuthMiddlewareAuthenticated:
    """Authenticated requests pass through to routes."""

    def test_authenticated_user_can_access_dashboard(self, app, client):
        _login_user(app, client)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_authenticated_user_can_access_accounts(self, app, client):
        _login_user(app, client)
        resp = client.get("/accounts")
        assert resp.status_code == 200

    def test_authenticated_user_can_access_vms(self, app, client):
        _login_user(app, client)
        resp = client.get("/vms")
        assert resp.status_code == 200


class TestAuthMiddlewareUnauthenticated:
    """Unauthenticated requests redirect to /auth/login."""

    def test_unauthenticated_dashboard_redirects_to_login(self, app, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert "/auth/login" in resp.headers["location"]

    def test_unauthenticated_accounts_redirects_to_login(self, app, client):
        resp = client.get("/accounts", follow_redirects=False)
        assert resp.status_code == 307
        assert "/auth/login" in resp.headers["location"]

    def test_unauthenticated_vms_redirects_to_login(self, app, client):
        resp = client.get("/vms", follow_redirects=False)
        assert resp.status_code == 307
        assert "/auth/login" in resp.headers["location"]

    def test_unauthenticated_comparison_redirects_to_login(self, app, client):
        resp = client.get("/comparison", follow_redirects=False)
        assert resp.status_code == 307
        assert "/auth/login" in resp.headers["location"]


class TestAuthMiddlewareExcludedPaths:
    """Excluded paths are accessible without auth."""

    def test_auth_login_accessible_without_session(self, app, client):
        from starlette.responses import RedirectResponse
        _mock_oauth(
            app,
            authorize_redirect_rv=RedirectResponse("https://idp.example.com/auth"),
        )
        resp = client.get("/auth/login", follow_redirects=False)
        # Should reach the route (307 redirect to IdP), not be blocked by middleware
        assert resp.status_code == 307
        assert "idp.example.com" in resp.headers["location"]

    def test_auth_callback_accessible_without_session(self, app, client):
        _mock_oauth(app, authorize_access_token_rv={
            "userinfo": {
                "sub": "user-1",
                "name": "Test",
                "email": "t@e.com",
                "roles": ["infraverse-admin"],
            },
        })
        resp = client.get("/auth/callback", follow_redirects=False)
        # Should reach the callback route, not be blocked
        assert resp.status_code == 302

    def test_auth_logout_accessible_without_session(self, app, client):
        resp = client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["location"]

    def test_health_accessible_without_session(self, app, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestAuthMiddlewareSessionExpiry:
    """Expired session cookie redirects to login."""

    def test_expired_session_redirects_to_login(self):
        """Session with max_age=1 expires after sleep, causing redirect."""
        oidc_cfg = OidcConfig(
            provider_url="https://idp.example.com/realms/test",
            client_id="infraverse",
            client_secret="test-secret-key-for-sessions-xxxxx",
            required_role="infraverse-admin",
        )
        inf_cfg = InfraverseConfig(oidc=oidc_cfg)
        app = create_app(
            "sqlite:///:memory:",
            infraverse_config=inf_cfg,
            session_max_age=1,
        )
        client = TestClient(app)

        _login_user(app, client)

        # Verify access works before expiry
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 200

        # Wait for session to expire
        time.sleep(2)

        # Now the session cookie should be expired
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert "/auth/login" in resp.headers["location"]


class TestAuthMiddlewareRoleCheck:
    """Role-based access control via session."""

    def test_user_with_required_role_gets_access(self, app, client):
        _login_user(app, client, roles=["infraverse-admin"])
        resp = client.get("/")
        assert resp.status_code == 200

    def test_user_without_role_in_session_gets_403(self, app, client):
        """If session has has_role=False, user gets 403 on protected routes."""
        # First log in with a valid role so we have an authenticated session
        _login_user(app, client)

        # Add a test endpoint to downgrade the session role
        @app.get("/test/downgrade-session")
        async def downgrade_session(request: Request):
            request.session["user"] = {
                "name": "Bad User",
                "email": "bad@example.com",
                "has_role": False,
            }
            return JSONResponse({"ok": True})

        # Downgrade the session (we're authenticated so middleware lets us through)
        client.get("/test/downgrade-session")

        # Now access a protected route — should get 403
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 403
