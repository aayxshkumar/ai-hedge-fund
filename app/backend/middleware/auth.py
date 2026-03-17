"""Bearer token authentication middleware.

Uses an **allow-list** model: every route is protected unless it matches
one of the PUBLIC_PREFIXES.  This prevents new endpoints from being
accidentally exposed without auth.

Set ``API_AUTH_TOKEN`` in .env to enable.  When the variable is unset or
empty the middleware is a no-op so local development isn't gated.
"""

from __future__ import annotations

import hmac
import os
import logging

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger(__name__)

PUBLIC_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests to non-public routes unless a valid bearer token is supplied."""

    def __init__(self, app, token: str | None = None):
        super().__init__(app)
        self.token = token or os.getenv("API_AUTH_TOKEN", "")

    async def dispatch(self, request: Request, call_next):
        if not self.token:
            return await call_next(request)

        path = request.url.path

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], self.token):
            raise HTTPException(status_code=401, detail="Unauthorized")

        return await call_next(request)
