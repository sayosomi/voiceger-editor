"""Authenticated HTTP adapters for one-item Take and Preview workflows."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, StrictBool

from .web_routes import _translate_error
from .web_security import require_web_access, require_web_mutation
from .web_sessions import (
    WebSessionCapacity, WebSessionClosed, WebSessionConflict,
    WebSessionNotFound, WebSessionOperations,
)
from .web_takes import WebTakeValidation


class PreparationPayload(BaseModel):
    rebuild: StrictBool = False


def _call(action):
    try:
        return action()
    except (WebSessionConflict, WebSessionNotFound, WebSessionCapacity, WebSessionClosed) as exc:
        raise _translate_error(exc) from None
    except (ValueError, TypeError, WebTakeValidation):
        raise HTTPException(status_code=422, detail="Invalid audio operation") from None
    except Exception:
        raise HTTPException(status_code=503, detail="Audio operation unavailable") from None


def build_web_take_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(prefix="/api/web/sessions", include_in_schema=False)
    prefix = "/{session_id}/batch/items/{item_id}"

    @router.post(prefix + "/audio/prepare", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def prepare(session_id: str, item_id: str, payload: PreparationPayload,
                expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.start_prepare(
            session_id, item_id, expected_revision, rebuild=payload.rebuild,
        ))

    @router.post(prefix + "/audio/preview", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def preview(session_id: str, item_id: str,
                expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.start_preview(session_id, item_id, expected_revision))

    @router.post(prefix + "/takes/generate", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def generate(session_id: str, item_id: str,
                 expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.start_generate(session_id, item_id, expected_revision))

    @router.post(prefix + "/takes/regenerate", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def regenerate_all(session_id: str, item_id: str,
                       expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.start_regenerate(
            session_id, item_id, expected_revision,
        ))

    @router.post(prefix + "/takes/{number}/regenerate", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def regenerate_one(session_id: str, item_id: str, number: int,
                       expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.start_regenerate(
            session_id, item_id, expected_revision, number=number,
        ))

    @router.post(prefix + "/takes/{number}/accept", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def accept(session_id: str, item_id: str, number: int,
               expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.start_accept(
            session_id, item_id, expected_revision, number,
        ))

    @router.delete(prefix + "/takes", dependencies=[Depends(require_web_mutation)])
    def clear(session_id: str, item_id: str,
              expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.clear_candidates(
            session_id, item_id, expected_revision,
        ))

    @router.get(prefix + "/takes/{number}/audio",
                dependencies=[Depends(require_web_access)])
    def take_audio(session_id: str, item_id: str, number: int):
        data = _call(lambda: service.candidate_audio(session_id, item_id, number))
        return Response(content=data, media_type="audio/wav")

    @router.get(prefix + "/audio/preview/{handle}",
                dependencies=[Depends(require_web_access)])
    def preview_audio(session_id: str, item_id: str, handle: str):
        data = _call(lambda: service.preview_bytes(session_id, item_id, handle))
        return Response(content=data, media_type="audio/wav")

    return router
