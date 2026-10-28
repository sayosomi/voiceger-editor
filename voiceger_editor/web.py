"""Read-only, mobile-first Web UI composition root.

The VOICEVOX-compatible API and mutable TUI session core remain separate.
Future state-changing Web APIs require their own security contract.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ._version import __version__


ASSETS = Path(__file__).resolve().parent / "web_assets"
app = FastAPI(
    title="Voiceger Editor Web",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="web-assets")

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


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ASSETS / "index.html", media_type="text/html")


@app.get("/api/web/health", include_in_schema=False)
def health():
    """No Voiceger startup, local paths, host details or mutable state."""
    return {"name": "voiceger-editor-web", "version": __version__, "status": "ok"}
