"""Tests for CSRF token generation, session storage, and validation."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from infraverse.config_file import InfraverseConfig, OidcConfig
from infraverse.web.app import create_app
from infraverse.web.csrf import generate_csrf_token, get_csrf_token


# --- Unit tests for token generation and session storage ---


class TestGenerateCsrfToken:
    """CSRF token generation produces unique, URL-safe tokens."""

    def test_returns_nonempty_string(self):
        token = generate_csrf_token()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_tokens_are_unique(self):
        tokens = {generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_token_is_url_safe(self):
        token = generate_csrf_token()
        # token_urlsafe produces only alphanumerics, hyphens, underscores
        assert all(c.isalnum() or c in "-_" for c in token)


class TestGetCsrfToken:
    """get_csrf_token reads from session or creates new token."""

    def test_creates_token_when_absent(self):
        session = {}
        token = get_csrf_token(session)
        assert token
        assert session["csrf_token"] == token

    def test_returns_existing_token(self):
        session = {"csrf_token": "existing-token"}
        token = get_csrf_token(session)
        assert token == "existing-token"

    def test_does_not_overwrite_existing_token(self):
        session = {"csrf_token": "keep-me"}
        get_csrf_token(session)
        assert session["csrf_token"] == "keep-me"


# --- Integration tests with CSRF middleware ---


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
    return TestClient(app, base_url="https://testserver")


def _mock_oauth(app, authorize_access_token_rv=None):
    mock_oidc = MagicMock()
    if authorize_access_token_rv is not None:
        mock_oidc.authorize_access_token = AsyncMock(
            return_value=authorize_access_token_rv,
        )
    app.state.oauth.oidc = mock_oidc
    return mock_oidc


def _login_user(app, client, roles=None):
    """Simulate OIDC login by calling callback with mocked token."""
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


def _get_csrf_token_from_session(app, client):
    """Load the dashboard to populate CSRF token, then extract it from page HTML."""
    resp = client.get("/")
    assert resp.status_code == 200
    # Extract token from the hx-headers attribute in HTML
    import re
    match = re.search(r'X-CSRF-Token":\s*"([^"]+)"', resp.text)
    assert match, "CSRF token not found in dashboard HTML"
    return match.group(1)


class TestCSRFTokenInSession:
    """CSRF token is generated and stored in session on page load."""

    def test_dashboard_page_contains_csrf_token(self, app, client):
        _login_user(app, client)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "X-CSRF-Token" in resp.text

    def test_csrf_token_is_nonempty_in_html(self, app, client):
        _login_user(app, client)
        token = _get_csrf_token_from_session(app, client)
        assert len(token) > 0

    def test_csrf_token_stable_across_requests(self, app, client):
        """Same session gets the same CSRF token on subsequent GETs."""
        _login_user(app, client)
        token1 = _get_csrf_token_from_session(app, client)
        token2 = _get_csrf_token_from_session(app, client)
        assert token1 == token2


class TestCSRFValidationRejectsWithout:
    """POST requests without valid CSRF token are rejected with 403."""

    def test_post_without_csrf_token_returns_403(self, app, client):
        _login_user(app, client)
        resp = client.post("/sync/trigger")
        assert resp.status_code == 403

    def test_post_with_empty_csrf_header_returns_403(self, app, client):
        _login_user(app, client)
        resp = client.post(
            "/sync/trigger", headers={"X-CSRF-Token": ""}
        )
        assert resp.status_code == 403

    def test_post_with_wrong_csrf_token_returns_403(self, app, client):
        _login_user(app, client)
        # Load page to generate token, then submit wrong one
        _get_csrf_token_from_session(app, client)
        resp = client.post(
            "/sync/trigger", headers={"X-CSRF-Token": "wrong-token"}
        )
        assert resp.status_code == 403

    def test_403_json_response_has_detail(self, app, client):
        _login_user(app, client)
        resp = client.post("/sync/trigger")
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    def test_403_htmx_returns_html(self, app, client):
        _login_user(app, client)
        resp = client.post(
            "/sync/trigger",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 403
        assert "text/html" in resp.headers["content-type"]
        assert "CSRF" in resp.text


class TestCSRFValidationAccepts:
    """POST requests with valid CSRF token pass through."""

    def test_post_with_valid_csrf_token_succeeds(self, app, client):
        _login_user(app, client)
        token = _get_csrf_token_from_session(app, client)
        resp = client.post(
            "/sync/trigger", headers={"X-CSRF-Token": token}
        )
        # 503 = scheduler not configured, but NOT 403 = CSRF passed
        assert resp.status_code == 503

    def test_post_htmx_with_valid_csrf_token_succeeds(self, app, client):
        _login_user(app, client)
        token = _get_csrf_token_from_session(app, client)
        resp = client.post(
            "/sync/trigger",
            headers={"X-CSRF-Token": token, "HX-Request": "true"},
        )
        # 200 with warning HTML (scheduler not configured) means CSRF passed
        assert resp.status_code == 200
        assert "Scheduler not configured" in resp.text

    def test_csrf_token_reusable_across_multiple_posts(self, app, client):
        """Same token can be used for multiple POST requests."""
        _login_user(app, client)
        token = _get_csrf_token_from_session(app, client)
        for _ in range(3):
            resp = client.post(
                "/sync/trigger", headers={"X-CSRF-Token": token}
            )
            assert resp.status_code == 503  # CSRF passed, scheduler not configured


class TestCSRFExcludedPaths:
    """CSRF validation is skipped for excluded paths."""

    def test_health_endpoint_no_csrf_needed(self, app, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_auth_paths_no_csrf_needed(self, app, client):
        resp = client.get("/auth/logout", follow_redirects=False)
        # Should reach the route, not be blocked by CSRF
        assert resp.status_code == 302
