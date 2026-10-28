"""Narrow authenticated Web session and runtime-operation HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .web_security import require_web_access, require_web_mutation
from .web_sessions import (
    WebSessionCapacity,
    WebSessionClosed,
    WebSessionConflict,
    WebSessionNotFound,
    WebSessionOperations,
)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WebSessionNotFound):
        return HTTPException(status_code=404, detail="Not found")
    if isinstance(exc, WebSessionConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, WebSessionCapacity):
        return HTTPException(status_code=429, detail="Web session limit reached")
    if isinstance(exc, WebSessionClosed):
        return HTTPException(status_code=503, detail="Web session service stopped")
    raise exc


def build_web_session_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(prefix="/api/web", include_in_schema=False)

    @router.post("/sessions", status_code=201, dependencies=[Depends(require_web_mutation)])
    def create_session():
        try:
            return service.create()
        except (WebSessionClosed, WebSessionCapacity) as exc:
            raise _translate_error(exc) from None

    @router.get("/sessions/{session_id}", dependencies=[Depends(require_web_access)])
    def get_session(session_id: str):
        try:
            return service.get(session_id)
        except (WebSessionClosed, WebSessionNotFound) as exc:
            raise _translate_error(exc) from None

    @router.delete(
        "/sessions/{session_id}",
        status_code=204,
        dependencies=[Depends(require_web_mutation)],
    )
    def close_session(session_id: str):
        try:
            service.delete(session_id)
        except (WebSessionClosed, WebSessionNotFound, WebSessionConflict) as exc:
            raise _translate_error(exc) from None

    @router.post(
        "/sessions/{session_id}/operations/runtime-check",
        status_code=202,
        dependencies=[Depends(require_web_mutation)],
    )
    def begin_runtime_check(session_id: str):
        try:
            return service.submit_runtime_check(session_id)
        except (WebSessionClosed, WebSessionNotFound, WebSessionConflict) as exc:
            raise _translate_error(exc) from None

    @router.get(
        "/sessions/{session_id}/operations/{operation_id}",
        dependencies=[Depends(require_web_access)],
    )
    def get_operation(session_id: str, operation_id: str):
        try:
            return service.get_operation(session_id, operation_id)
        except (WebSessionClosed, WebSessionNotFound) as exc:
            raise _translate_error(exc) from None

    @router.post(
        "/sessions/{session_id}/operations/{operation_id}/cancel",
        dependencies=[Depends(require_web_mutation)],
    )
    def cancel_operation(session_id: str, operation_id: str):
        try:
            return service.cancel(session_id, operation_id)
        except (WebSessionClosed, WebSessionNotFound) as exc:
            raise _translate_error(exc) from None

    return router
