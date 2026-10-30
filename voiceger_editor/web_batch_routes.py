"""Authenticated HTTP adapters for frontend-neutral Batch List operations."""

from __future__ import annotations

from typing import Callable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr

from .web_batch import WebBatchValidation
from .web_routes import _translate_error
from .web_security import require_web_access, require_web_mutation
from .web_sessions import (
    WebSessionCapacity,
    WebSessionClosed,
    WebSessionConflict,
    WebSessionNotFound,
    WebSessionOperations,
)


class CaptionsPayload(BaseModel):
    text: StrictStr = Field(max_length=32000)


class DeleteSelectionPayload(BaseModel):
    ids: List[StrictStr] = Field(min_items=1, max_items=200)


class CaptionPayload(BaseModel):
    caption: StrictStr = Field(max_length=2000)


class IncludedPayload(BaseModel):
    included: StrictBool


class PositionPayload(BaseModel):
    index: StrictInt


class CountPayload(BaseModel):
    count: StrictInt


class OptionalCountPayload(BaseModel):
    count: Optional[StrictInt]


def _call(action: Callable):
    try:
        return action()
    except (WebSessionNotFound, WebSessionConflict, WebSessionClosed, WebSessionCapacity) as exc:
        raise _translate_error(exc) from None
    except (WebBatchValidation, ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid Batch value") from None
    except Exception:
        # Never expose local paths, Voiceger model names, or settings details.
        raise HTTPException(status_code=503, detail="Batch operation unavailable") from None


def build_web_batch_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(prefix="/api/web/sessions", include_in_schema=False)

    @router.get("/{session_id}/batch", dependencies=[Depends(require_web_access)])
    def get_batch(session_id: str):
        return _call(lambda: service.get_batch(session_id))

    @router.post("/{session_id}/batch/generate", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def generate_selected(
        session_id: str, expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.start_batch_generation(session_id, expected_revision))

    @router.post("/{session_id}/batch/items", dependencies=[Depends(require_web_mutation)])
    def add_captions(
        session_id: str, payload: CaptionsPayload, expected_revision: int = Query(..., ge=0),
    ):
        return _call(
            lambda: service.add_captions(session_id, expected_revision, payload.text)
        )

    @router.post("/{session_id}/batch/items/bulk-delete",
                 dependencies=[Depends(require_web_mutation)])
    def delete_selected_captions(
        session_id: str, payload: DeleteSelectionPayload,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.remove_captions(
            session_id, expected_revision, payload.ids
        ))

    @router.patch("/{session_id}/batch/items/{item_id}/caption",
                  dependencies=[Depends(require_web_mutation)])
    def edit_caption(
        session_id: str, item_id: str, payload: CaptionPayload,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.edit_caption(
            session_id, expected_revision, item_id, payload.caption
        ))

    @router.patch("/{session_id}/batch/items/{item_id}/included",
                  dependencies=[Depends(require_web_mutation)])
    def set_included(
        session_id: str, item_id: str, payload: IncludedPayload,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.set_included(
            session_id, expected_revision, item_id, payload.included
        ))

    @router.patch("/{session_id}/batch/items/{item_id}/position",
                  dependencies=[Depends(require_web_mutation)])
    def move_caption(
        session_id: str, item_id: str, payload: PositionPayload,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.move_caption(
            session_id, expected_revision, item_id, payload.index
        ))

    @router.patch("/{session_id}/batch/items/{item_id}/take-count",
                  dependencies=[Depends(require_web_mutation)])
    def set_item_take_count(
        session_id: str, item_id: str, payload: OptionalCountPayload,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.set_item_take_count(
            session_id, expected_revision, item_id, payload.count
        ))

    @router.patch("/{session_id}/batch/default-take-count",
                  dependencies=[Depends(require_web_mutation)])
    def set_default_take_count(
        session_id: str, payload: CountPayload,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.set_default_take_count(
            session_id, expected_revision, payload.count
        ))

    @router.delete("/{session_id}/batch/items/{item_id}",
                   dependencies=[Depends(require_web_mutation)])
    def delete_caption(
        session_id: str, item_id: str, expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.remove_caption(
            session_id, expected_revision, item_id
        ))

    return router
