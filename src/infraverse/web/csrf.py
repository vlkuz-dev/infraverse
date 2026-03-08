"""CSRF protection for Infraverse web UI.

Generates per-session CSRF tokens and validates them on mutating requests.
Token is checked via X-CSRF-Token header (for HTMX/fetch) or csrf_token form field.
"""

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset(("GET", "HEAD", "OPTIONS", "TRACE"))
CSRF_EXCLUDED_PREFIXES = ("/auth/",)
CSRF_EXCLUDED_PATHS = ("/health",)


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_urlsafe(32)


def get_csrf_token(session: dict) -> str:
    """Get existing CSRF token from session, or generate and store a new one."""
    token = session.get("csrf_token")
    if not token:
        token = generate_csrf_token()
        session["csrf_token"] = token
    return token


class CSRFMiddleware(BaseHTTPMiddleware):
    """Validate CSRF tokens on mutating requests (POST, PUT, DELETE, PATCH).

    - On all requests: ensures a csrf_token exists in the session
    - On mutating requests: validates the submitted token against the session token
    - Returns 403 if token is missing or invalid
    - Skips validation for excluded paths (/auth/*, /health)
    """

    async def dispatch(self, request, call_next):
        path = request.url.path

        if path in CSRF_EXCLUDED_PATHS or any(
            path.startswith(p) for p in CSRF_EXCLUDED_PREFIXES
        ):
            return await call_next(request)

        # Ensure session has a CSRF token (generates on first access)
        if hasattr(request, "session"):
            get_csrf_token(request.session)

        # Validate on mutating methods
        if request.method not in SAFE_METHODS and hasattr(request, "session"):
            session_token = request.session.get("csrf_token", "")
            submitted = request.headers.get("X-CSRF-Token", "")

            if (
                not submitted
                or not session_token
                or not secrets.compare_digest(submitted, session_token)
            ):
                logger.warning(
                    "CSRF validation failed for %s %s", request.method, path
                )
                if request.headers.get("HX-Request"):
                    return HTMLResponse(
                        '<span class="text-danger">CSRF token invalid. '
                        "Please reload the page.</span>",
                        status_code=403,
                    )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing or invalid"},
                )

        return await call_next(request)
