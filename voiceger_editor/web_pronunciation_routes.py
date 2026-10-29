"""Authenticated Web routes for pure-Japanese pronunciation drafts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictStr

from .web_pronunciation import WebPronunciationValidation
from .web_routes import _translate_error
from .web_security import require_web_mutation
from .web_sessions import (
    WebSessionCapacity, WebSessionClosed, WebSessionConflict,
    WebSessionNotFound, WebSessionOperations,
)


class PronunciationPayload(BaseModel):
    notation: StrictStr = Field(max_length=2000)


def _call(action):
    try:
        return action()
    except (WebSessionCapacity, WebSessionClosed, WebSessionConflict,
            WebSessionNotFound) as exc:
        raise _translate_error(exc) from None
    except WebPronunciationValidation as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code}) from None
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail={"code": "invalid_pronunciation"}) from None
    except Exception:
        raise HTTPException(status_code=503, detail="Pronunciation operation unavailable") from None


def build_web_pronunciation_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(prefix="/api/web/sessions", include_in_schema=False)
    path = "/{session_id}/batch/items/{item_id}/pronunciation"

    @router.post(path + "/preview", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def preview(session_id: str, item_id: str, payload: PronunciationPayload,
                expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.start_japanese_draft_preview(
            session_id, item_id, expected_revision, payload.notation,
        ))

    @router.patch(path, dependencies=[Depends(require_web_mutation)])
    def apply(session_id: str, item_id: str, payload: PronunciationPayload,
              expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.apply_japanese_pronunciation(
            session_id, item_id, expected_revision, payload.notation,
        ))

    return router
