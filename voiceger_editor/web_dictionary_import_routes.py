"""Authenticated filename-only Web dictionary import routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool, StrictStr

from .web_dictionary_import_source import WebDictionaryImportValidation
from .web_routes import _translate_error
from .web_security import require_web_access, require_web_mutation
from .web_sessions import (
    WebSessionClosed, WebSessionConflict, WebSessionNotFound, WebSessionOperations,
)


class ImportReview(BaseModel):
    filename: StrictStr = Field(min_length=1, max_length=200)
    expected_revision: StrictStr = Field(min_length=64, max_length=64)


class ImportToken(BaseModel):
    token: StrictStr = Field(min_length=1, max_length=128)


class ImportSelect(ImportToken):
    language: StrictStr
    identity: StrictStr
    selected: StrictBool


class ImportWordType(ImportToken):
    identity: StrictStr
    word_type: StrictStr


class ImportCommit(ImportToken):
    confirmed: StrictBool = False


def _call(action):
    try:
        return action()
    except (WebSessionClosed, WebSessionConflict, WebSessionNotFound) as exc:
        raise _translate_error(exc) from None
    except WebDictionaryImportValidation as exc:
        status = (
            409 if exc.code in {"review_expired", "source_changed", "confirmation_required"}
            else 503 if exc.code == "import_io" else 422
        )
        raise HTTPException(status_code=status, detail={"code": exc.code}) from None
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "import_io"}) from None


def build_web_dictionary_import_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(
        prefix="/api/web/sessions/{session_id}/dictionary/import",
        include_in_schema=False,
    )

    @router.get("/files", dependencies=[Depends(require_web_access)])
    def files(session_id: str):
        return _call(lambda: service.list_dictionary_import_files(session_id))

    @router.post("/review", dependencies=[Depends(require_web_mutation)])
    def review(session_id: str, payload: ImportReview):
        return _call(lambda: service.review_dictionary_import(
            session_id, payload.filename, payload.expected_revision,
        ))

    @router.post("/selection", dependencies=[Depends(require_web_mutation)])
    def selection(session_id: str, payload: ImportSelect):
        return _call(lambda: service.select_dictionary_import(
            session_id, payload.token, payload.language, payload.identity, payload.selected,
        ))

    @router.post("/clear", dependencies=[Depends(require_web_mutation)])
    def clear(session_id: str, payload: ImportToken):
        return _call(lambda: service.clear_dictionary_import_selection(session_id, payload.token))

    @router.post("/word-type", dependencies=[Depends(require_web_mutation)])
    def word_type(session_id: str, payload: ImportWordType):
        return _call(lambda: service.set_dictionary_import_word_type(
            session_id, payload.token, payload.identity, payload.word_type,
        ))

    @router.post("/commit", dependencies=[Depends(require_web_mutation)])
    def commit(session_id: str, payload: ImportCommit):
        return _call(lambda: service.commit_dictionary_import(
            session_id, payload.token, payload.confirmed,
        ))

    @router.post("/cancel", dependencies=[Depends(require_web_mutation)])
    def cancel(session_id: str, payload: ImportToken):
        return _call(lambda: service.cancel_dictionary_import(session_id, payload.token))

    return router
