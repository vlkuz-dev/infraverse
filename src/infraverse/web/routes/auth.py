"""OIDC authentication routes for Infraverse web UI."""

import logging

from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def setup_oauth(oidc_config) -> OAuth:
    """Configure OAuth client from OIDC config."""
    oauth = OAuth()
    oauth.register(
        name="oidc",
        server_metadata_url=f"{oidc_config.provider_url}/.well-known/openid-configuration",
        client_id=oidc_config.client_id,
        client_secret=oidc_config.client_secret,
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


def _extract_roles(userinfo: dict) -> list[str]:
    """Extract roles from userinfo, checking common OIDC role claim locations."""
    # Direct roles claim
    roles = userinfo.get("roles", [])
    if roles:
        return roles
    # Keycloak realm_access.roles
    realm_access = userinfo.get("realm_access", {})
    if isinstance(realm_access, dict):
        roles = realm_access.get("roles", [])
        if roles:
            return roles
    return []


@router.get("/login")
async def login(request: Request):
    """Redirect to OIDC provider for authentication."""
    oauth = request.app.state.oauth
    redirect_uri = request.url_for("callback")
    return await oauth.oidc.authorize_redirect(request, str(redirect_uri))


@router.get("/callback")
async def callback(request: Request):
    """Handle OIDC callback: validate token, check role, create session."""
    oauth = request.app.state.oauth
    oidc_config = request.app.state.infraverse_config.oidc

    try:
        token = await oauth.oidc.authorize_access_token(request)
    except OAuthError as e:
        logger.warning("OIDC token validation failed: %s", e)
        return HTMLResponse(content="Authentication failed", status_code=401)

    userinfo = token.get("userinfo", {})

    roles = _extract_roles(userinfo)
    if not roles:
        # Some OIDC providers (Keycloak, Azure AD) put roles in the ID token
        # claims rather than in the userinfo endpoint response
        id_token_claims = token.get("id_token", {})
        if isinstance(id_token_claims, dict):
            roles = _extract_roles(id_token_claims)

    if oidc_config.required_role not in roles:
        logger.warning(
            "User %s lacks required role '%s'",
            userinfo.get("email", "unknown"),
            oidc_config.required_role,
        )
        return HTMLResponse(
            content="Access denied: insufficient permissions",
            status_code=403,
        )

    request.session["user"] = {
        "name": userinfo.get("name", ""),
        "email": userinfo.get("email", ""),
        "has_role": True,
    }

    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=302)
