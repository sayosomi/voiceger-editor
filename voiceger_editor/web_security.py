"""Fail-closed authentication and browser request guards for mutable Web APIs.

Bearer tokens are configured out-of-band; no cookie-based login exists yet.
"""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


_TOKEN_ENV = "VOICEGER_WEB_TOKEN"


def require_web_access(request: Request) -> None:
    token = os.environ.get(_TOKEN_ENV, "")
    if len(token) < 32:
        raise HTTPException(
            status_code=503,
            detail="Web session access is not configured",
        )
    supplied = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not supplied.startswith(prefix) or not hmac.compare_digest(
        supplied[len(prefix):], token
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_web_mutation(request: Request) -> None:
    require_web_access(request)
    # Cross-site forms cannot add this header, and no permissive CORS is used.
    if request.headers.get("x-voiceger-web-request") != "1":
        raise HTTPException(status_code=403, detail="Request header required")

    origin = request.headers.get("origin")
    if origin is not None:
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin != expected:
            raise HTTPException(status_code=403, detail="Origin not allowed")
