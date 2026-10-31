"""Authenticated Web synthesis settings API."""

from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StrictFloat, StrictInt

from .web_routes import _translate_error
from .web_security import require_web_access, require_web_mutation
from .web_sessions import (
    WebSessionClosed, WebSessionConflict, WebSessionNotFound,
    WebSessionOperations,
)
from .web_settings import WebSettingsValidation


Number = Union[StrictFloat, StrictInt]


class ItemVoicePayload(BaseModel):
    style_id: StrictInt
    speed: Number


class CommonSynthesisPayload(BaseModel):
    style_id: StrictInt
    speed: Number
    top_k: StrictInt
    top_p: Number
    temperature: Number


def _call(action):
    try:
        return action()
    except (WebSessionClosed, WebSessionConflict, WebSessionNotFound) as exc:
        raise _translate_error(exc) from None
    except WebSettingsValidation:
        raise HTTPException(status_code=422, detail="Invalid or unavailable setting") from None
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid setting") from None
    except Exception:
        raise HTTPException(status_code=503, detail="Settings are unavailable on the Mac") from None


def build_web_settings_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(prefix="/api/web/sessions", include_in_schema=False)

    @router.get("/{session_id}/settings", dependencies=[Depends(require_web_access)])
    def get_settings(session_id: str):
        return _call(lambda: service.get_web_settings(session_id))

    @router.patch("/{session_id}/settings", dependencies=[Depends(require_web_mutation)])
    def save_synthesis(
        session_id: str, payload: CommonSynthesisPayload,
        expected_revision: int = Query(..., ge=0),
        expected_settings_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.save_common_synthesis(
            session_id, expected_revision, expected_settings_revision,
            **payload.dict(),
        ))

    @router.patch("/{session_id}/batch/items/{item_id}/voice",
                  dependencies=[Depends(require_web_mutation)])
    def save_item_voice(
        session_id: str, item_id: str, payload: ItemVoicePayload,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.set_item_voice(
            session_id, expected_revision, item_id, **payload.dict(),
        ))

    return router
