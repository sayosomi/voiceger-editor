"""Protected Web dictionary API; compatibility dictionary endpoints remain separate."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, StrictInt

from .web_dictionary import WebDictionaryValidation
from .web_routes import _translate_error
from .web_security import require_web_access, require_web_mutation
from .web_sessions import (
    WebSessionCapacity, WebSessionClosed, WebSessionConflict,
    WebSessionNotFound, WebSessionOperations,
)
from .user_dictionary import UserDictionaryInputError, UserDictionaryStorageError
from .openjtalk_dictionary import OpenJTalkDictionaryError


class DictionaryWordPayload(BaseModel):
    expected_revision: str = Field(min_length=64, max_length=64)
    language: str
    surface: str = Field(max_length=2000)
    notation: str = Field(max_length=2000)
    word_type: str = "PROPER_NOUN"
    priority: StrictInt = 5


class DictionaryDraftPayload(BaseModel):
    language: str
    surface: str = Field(max_length=2000)
    notation: str = Field(default="", max_length=2000)


class DictionaryGeneratePayload(BaseModel):
    language: str
    surface: str = Field(max_length=2000)


def _call(action):
    try:
        return action()
    except (WebSessionConflict, WebSessionNotFound, WebSessionCapacity, WebSessionClosed) as exc:
        raise _translate_error(exc) from None
    except (UserDictionaryInputError, WebDictionaryValidation, ValueError, TypeError):
        raise HTTPException(status_code=422, detail={"code": "invalid_dictionary"}) from None
    except (UserDictionaryStorageError, OpenJTalkDictionaryError):
        raise HTTPException(status_code=503, detail={"code": "dictionary_io"}) from None
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "dictionary_unavailable"}) from None


def build_web_dictionary_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(prefix="/api/web/sessions/{session_id}/dictionary",
                       include_in_schema=False)

    @router.get("/{language}", dependencies=[Depends(require_web_access)])
    def get_words(session_id: str, language: str,
                  sort: str = Query("surface_asc", max_length=24),
                  query: str = Query("", max_length=200),
                  word_type: str = Query("ALL", max_length=20)):
        return _call(lambda: service.list_dictionary(session_id, language, sort, query, word_type))

    @router.post("/words", dependencies=[Depends(require_web_mutation)])
    def add_word(session_id: str, payload: DictionaryWordPayload):
        return _call(lambda: service.save_dictionary_word(session_id, payload))

    @router.put("/words/{word_id:path}", dependencies=[Depends(require_web_mutation)])
    def replace_word(session_id: str, word_id: str, payload: DictionaryWordPayload):
        return _call(lambda: service.save_dictionary_word(session_id, payload, word_id))

    @router.delete("/words/{word_id:path}", dependencies=[Depends(require_web_mutation)])
    def remove_word(session_id: str, word_id: str, language: str,
                    expected_revision: str = Query(..., min_length=64, max_length=64)):
        return _call(lambda: service.delete_dictionary_word(
            session_id, language, word_id, expected_revision))

    @router.post("/pronunciation/validate",
                 dependencies=[Depends(require_web_mutation)])
    def validate(session_id: str, payload: DictionaryDraftPayload):
        return _call(lambda: service.validate_dictionary_pronunciation(
            session_id, payload.language, payload.surface, payload.notation))

    @router.post("/pronunciation/generate", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def generate(session_id: str, payload: DictionaryGeneratePayload):
        return _call(lambda: service.start_dictionary_generate(
            session_id, payload.language, payload.surface))

    @router.post("/pronunciation/preview", status_code=202,
                 dependencies=[Depends(require_web_mutation)])
    def preview(session_id: str, payload: DictionaryDraftPayload):
        return _call(lambda: service.start_dictionary_preview(
            session_id, payload.language, payload.surface, payload.notation))

    @router.get("/audio/preview/{handle}", dependencies=[Depends(require_web_access)])
    def audio(session_id: str, handle: str):
        data = _call(lambda: service.dictionary_preview_bytes(session_id, handle))
        return Response(content=data, media_type="audio/wav")

    return router
