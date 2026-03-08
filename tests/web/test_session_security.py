"""Tests for session secret resolution and secure cookie flags."""

import hashlib

from infraverse.config_file import OidcConfig
from infraverse.web.app import _resolve_session_secret, create_app


class TestResolveSessionSecret:
    """Session secret resolution: env var > config > OIDC-derived."""

    def _make_oidc(self, session_secret=None):
        return OidcConfig(
            provider_url="https://idp.example.com/realms/test",
            client_id="infraverse",
            client_secret="test-client-secret",
            required_role="admin",
            session_secret=session_secret,
        )

    def test_env_var_takes_highest_priority(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "from-env")
        oidc = self._make_oidc(session_secret="from-config")
        assert _resolve_session_secret(oidc) == "from-env"

    def test_config_session_secret_used_when_no_env(self, monkeypatch):
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        oidc = self._make_oidc(session_secret="from-config")
        assert _resolve_session_secret(oidc) == "from-config"

    def test_oidc_derived_fallback(self, monkeypatch):
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        oidc = self._make_oidc()
        expected = hashlib.sha256(
            b"infraverse-session:" + b"test-client-secret"
        ).hexdigest()
        assert _resolve_session_secret(oidc) == expected

    def test_empty_env_var_falls_through(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "")
        oidc = self._make_oidc(session_secret="from-config")
        assert _resolve_session_secret(oidc) == "from-config"


class TestSessionCookieFlags:
    """SessionMiddleware cookie flags: production vs debug mode."""

    def _make_infraverse_config(self):
        from infraverse.config_file import InfraverseConfig

        oidc = OidcConfig(
            provider_url="https://idp.example.com/realms/test",
            client_id="infraverse",
            client_secret="test-secret-key-for-sessions-xxxxx",
            required_role="admin",
        )
        return InfraverseConfig(oidc=oidc)

    def _get_session_middleware_kwargs(self, app):
        """Extract SessionMiddleware kwargs from app.user_middleware."""
        from starlette.middleware.sessions import SessionMiddleware as SM

        for mw in app.user_middleware:
            if mw.cls is SM:
                return mw.kwargs
        return None

    def test_production_mode_https_only_true(self, monkeypatch):
        monkeypatch.delenv("INFRAVERSE_DEBUG", raising=False)
        cfg = self._make_infraverse_config()
        app = create_app("sqlite:///:memory:", infraverse_config=cfg)
        kwargs = self._get_session_middleware_kwargs(app)
        assert kwargs is not None, "SessionMiddleware not found"
        assert kwargs["https_only"] is True

    def test_production_mode_same_site_strict(self, monkeypatch):
        monkeypatch.delenv("INFRAVERSE_DEBUG", raising=False)
        cfg = self._make_infraverse_config()
        app = create_app("sqlite:///:memory:", infraverse_config=cfg)
        kwargs = self._get_session_middleware_kwargs(app)
        assert kwargs is not None
        assert kwargs["same_site"] == "strict"

    def test_debug_mode_https_only_false(self, monkeypatch):
        monkeypatch.setenv("INFRAVERSE_DEBUG", "true")
        cfg = self._make_infraverse_config()
        app = create_app("sqlite:///:memory:", infraverse_config=cfg)
        kwargs = self._get_session_middleware_kwargs(app)
        assert kwargs is not None
        assert kwargs["https_only"] is False

    def test_debug_mode_same_site_lax(self, monkeypatch):
        monkeypatch.setenv("INFRAVERSE_DEBUG", "true")
        cfg = self._make_infraverse_config()
        app = create_app("sqlite:///:memory:", infraverse_config=cfg)
        kwargs = self._get_session_middleware_kwargs(app)
        assert kwargs is not None
        assert kwargs["same_site"] == "lax"

    def test_debug_mode_flag_variations(self, monkeypatch):
        """INFRAVERSE_DEBUG accepts 1, true, yes (case-insensitive)."""
        cfg = self._make_infraverse_config()
        for val in ("1", "True", "YES", "true"):
            monkeypatch.setenv("INFRAVERSE_DEBUG", val)
            app = create_app("sqlite:///:memory:", infraverse_config=cfg)
            kwargs = self._get_session_middleware_kwargs(app)
            assert kwargs is not None
            assert kwargs["https_only"] is False, f"Failed for INFRAVERSE_DEBUG={val}"

    def test_non_debug_values_stay_production(self, monkeypatch):
        """Unrecognized INFRAVERSE_DEBUG values default to production mode."""
        cfg = self._make_infraverse_config()
        for val in ("0", "false", "no", "random"):
            monkeypatch.setenv("INFRAVERSE_DEBUG", val)
            app = create_app("sqlite:///:memory:", infraverse_config=cfg)
            kwargs = self._get_session_middleware_kwargs(app)
            assert kwargs is not None
            assert kwargs["https_only"] is True, f"Failed for INFRAVERSE_DEBUG={val}"
