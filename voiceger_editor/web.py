"""Mobile-first Web composition root, separate from the compatibility API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ._version import __version__
from .web_routes import build_web_session_router
from .web_batch_routes import build_web_batch_router
from .web_recipe_routes import build_web_recipe_router
from .web_take_routes import build_web_take_router
from .web_pronunciation_routes import build_web_pronunciation_router
from .web_section_routes import build_web_section_router
from .web_dictionary_routes import build_web_dictionary_router
from .web_dictionary_export_routes import build_web_dictionary_export_router
from .web_dictionary_import_routes import build_web_dictionary_import_router
from .web_sessions import WebSessionOperations
from .web_settings_routes import build_web_settings_router


ASSETS = Path(__file__).resolve().parent / "web_assets"
_MAX_MUTATION_BODY_BYTES = 1024 * 1024

_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self'; media-src blob:; "
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
    web_app.include_router(build_web_batch_router(session_service))
    web_app.include_router(build_web_settings_router(session_service))
    web_app.include_router(build_web_recipe_router(session_service))
    web_app.include_router(build_web_take_router(session_service))
    web_app.include_router(build_web_pronunciation_router(session_service))
    web_app.include_router(build_web_section_router(session_service))
    web_app.include_router(build_web_dictionary_router(session_service))
    web_app.include_router(build_web_dictionary_export_router(session_service))
    web_app.include_router(build_web_dictionary_import_router(session_service))

    @web_app.middleware("http")
    async def add_security_headers(request, call_next):
        response = None
        if (request.url.path.startswith("/api/web/") and
                request.method in {"POST", "PUT", "PATCH", "DELETE"}):
            # Pydantic field limits run only AFTER the HTTP body is buffered.
            # Bound total bytes for both Content-Length and streamed requests.
            declared = request.headers.get("content-length")
            if declared is not None:
                try:
                    invalid_length = not 0 <= int(declared) <= _MAX_MUTATION_BODY_BYTES
                except ValueError:
                    invalid_length = True
                if invalid_length:
                    response = JSONResponse(
                        status_code=413, content={"detail": "Request body too large"},
                    )
            if response is None:
                chunks = []
                total = 0
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > _MAX_MUTATION_BODY_BYTES:
                        response = JSONResponse(
                            status_code=413, content={"detail": "Request body too large"},
                        )
                        break
                    chunks.append(chunk)
                if response is None:
                    # Starlette replays the cached body to the route after
                    # this middleware; never buffer more than the limit.
                    request._body = b"".join(chunks)
        if response is None:
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
