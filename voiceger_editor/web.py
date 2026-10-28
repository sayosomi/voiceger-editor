"""Mobile-first Web composition root, separate from the compatibility API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ._version import __version__
from .web_routes import build_web_session_router
from .web_sessions import WebSessionOperations


ASSETS = Path(__file__).resolve().parent / "web_assets"

_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)


def create_web_app(*, service: WebSessionOperations | None = None) -> FastAPI:
    """Make isolated Web state for one process; no shared TUI/API state."""

    session_service = service if service is not None else WebSessionOperations()
    web_app = FastAPI(
        title="Voiceger Editor Web",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    web_app.state.web_sessions = session_service
    web_app.add_event_handler("shutdown", session_service.shutdown)
    web_app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="web-assets")
    web_app.include_router(build_web_session_router(session_service))

    @web_app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @web_app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ASSETS / "index.html", media_type="text/html")

    @web_app.get("/api/web/health", include_in_schema=False)
    def health():
        """No local paths, Voiceger model details or mutable session state."""
        return {"name": "voiceger-editor-web", "version": __version__, "status": "ok"}

    return web_app


app = create_web_app()
