"""Auth middleware for Infraverse web UI.

Checks session for authenticated user, redirects to /auth/login if not found.
Skips auth check for excluded paths: /auth/*, /static/*, /health.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

EXCLUDED_PREFIXES = ("/auth/", "/static/")
EXCLUDED_PATHS = ("/health",)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces authentication on all routes except excluded paths."""

    async def dispatch(self, request, call_next):
        path = request.url.path

        # Skip auth for excluded paths
        if path in EXCLUDED_PATHS or any(path.startswith(p) for p in EXCLUDED_PREFIXES):
            return await call_next(request)

        # Check session for user
        user = request.session.get("user") if hasattr(request, "session") else None

        if not user:
            return RedirectResponse(url="/auth/login", status_code=307)

        # Check role
        if not user.get("has_role", False):
            return HTMLResponse(
                content="Access denied: insufficient permissions",
                status_code=403,
            )

        return await call_next(request)
