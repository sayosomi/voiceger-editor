"""Authenticated, revision-guarded Web section-management endpoints."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, StrictInt, StrictStr

from .web_pronunciation_routes import _call
from .web_security import require_web_mutation
from .web_sessions import WebSessionOperations


class SectionTextPayload(BaseModel):
    language: Literal["ja", "en"]
    index: Optional[StrictInt]
    opening: StrictStr = Field(max_length=2000)
    text: StrictStr = Field(max_length=2000)


class SectionAppendPayload(BaseModel):
    language: Literal["ja", "en"]
    text: StrictStr = Field(max_length=2000)


class SectionDeletePayload(BaseModel):
    language: Literal["ja", "en"]
    index: StrictInt = Field(ge=0)
    opening: StrictStr = Field(max_length=2000)


def build_web_section_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(prefix="/api/web/sessions", include_in_schema=False)
    path = "/{session_id}/batch/items/{item_id}/sections"
    protected = [Depends(require_web_mutation)]

    @router.post(path + "/text/preview", status_code=202, dependencies=protected)
    def preview(session_id: str, item_id: str, payload: SectionTextPayload,
                expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.start_section_text_preview(
            session_id, item_id, expected_revision, payload.language,
            payload.index, payload.opening, payload.text))

    @router.patch(path + "/text", dependencies=protected)
    def change(session_id: str, item_id: str, payload: SectionTextPayload,
               expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.apply_section_text(
            session_id, item_id, expected_revision, payload.language,
            payload.index, payload.opening, payload.text))

    @router.post(path, dependencies=protected)
    def append(session_id: str, item_id: str, payload: SectionAppendPayload,
               expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.append_section(
            session_id, item_id, expected_revision, payload.language, payload.text))

    @router.post(path + "/delete", dependencies=protected)
    def delete(session_id: str, item_id: str, payload: SectionDeletePayload,
               expected_revision: int = Query(..., ge=0)):
        return _call(lambda: service.delete_section(
            session_id, item_id, expected_revision, payload.language,
            payload.index, payload.opening))

    return router
