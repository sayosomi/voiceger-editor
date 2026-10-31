"""Protected two-phase dictionary export routes; no client file paths."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool

from .web_dictionary_export import WebDictionaryExportValidation
from .web_routes import _translate_error
from .web_security import require_web_mutation
from .web_sessions import (
    WebSessionCapacity, WebSessionClosed, WebSessionConflict,
    WebSessionNotFound, WebSessionOperations,
)


class ExportReviewPayload(BaseModel):
    format: str = Field(max_length=16)
    expected_revision: str = Field(min_length=64, max_length=64)


class ExportCommitPayload(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    expected_revision: str = Field(min_length=64, max_length=64)
    confirmed_pitch_loss: StrictBool = False


class ExportCancelPayload(BaseModel):
    token: str = Field(min_length=1, max_length=128)


def _call(action):
    try:
        return action()
    except (
        WebSessionCapacity, WebSessionClosed, WebSessionConflict, WebSessionNotFound,
    ) as exc:
        raise _translate_error(exc) from None
    except WebDictionaryExportValidation as exc:
        status = (
            409 if exc.code in {
                "review_expired", "pitch_loss_confirmation_required",
            } else 503 if exc.code == "export_io" else 422
        )
        raise HTTPException(
            status_code=status, detail={"code": exc.code},
        ) from None
    except Exception:
        raise HTTPException(
            status_code=503, detail={"code": "export_io"},
        ) from None


def build_web_dictionary_export_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(
        prefix="/api/web/sessions/{session_id}/dictionary/export",
        include_in_schema=False,
    )

    @router.post("/review", dependencies=[Depends(require_web_mutation)])
    def review(session_id: str, payload: ExportReviewPayload):
        return _call(lambda: service.review_dictionary_export(
            session_id, payload.format, payload.expected_revision,
        ))

    @router.post("/commit", dependencies=[Depends(require_web_mutation)])
    def commit(session_id: str, payload: ExportCommitPayload):
        return _call(lambda: service.commit_dictionary_export(
            session_id, payload.token, payload.expected_revision,
            payload.confirmed_pitch_loss,
        ))

    @router.post("/cancel", dependencies=[Depends(require_web_mutation)])
    def cancel(session_id: str, payload: ExportCancelPayload):
        return _call(lambda: service.cancel_dictionary_export(
            session_id, payload.token,
        ))

    return router
