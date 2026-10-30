"""Authenticated, filename-only Mac Output Batch recipe routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StrictBool, StrictStr

from .web_recipe import WebRecipeValidation
from .web_routes import _translate_error
from .web_security import require_web_access, require_web_mutation
from .web_sessions import (
    WebSessionClosed, WebSessionConflict, WebSessionNotFound,
    WebSessionOperations,
)


class RecipeFilename(BaseModel):
    filename: StrictStr


class ReviewToken(BaseModel):
    token: StrictStr


class SaveToken(ReviewToken):
    confirmed_overwrite: StrictBool = False


class ReadToken(ReviewToken):
    confirmed_replace: StrictBool = False


def _call(action):
    try:
        return action()
    except (WebSessionClosed, WebSessionNotFound, WebSessionConflict) as exc:
        raise _translate_error(exc) from None
    except WebRecipeValidation as exc:
        status = 409 if exc.code in {"recipe_changed", "review_expired"} else (
            503 if exc.code == "recipe_io" else 422
        )
        detail = {"code": exc.code}
        if exc.item_index is not None:
            detail["item_index"] = exc.item_index
        raise HTTPException(status_code=status, detail=detail) from None
    except Exception:
        raise HTTPException(status_code=503, detail="Recipe operation unavailable") from None


def build_web_recipe_router(service: WebSessionOperations) -> APIRouter:
    router = APIRouter(
        prefix="/api/web/sessions/{session_id}/batch/recipes",
        include_in_schema=False,
    )

    @router.get("", dependencies=[Depends(require_web_access)])
    def list_recipes(session_id: str):
        return _call(lambda: service.list_recipes(session_id))

    @router.post("/save/review", dependencies=[Depends(require_web_mutation)])
    def review_save(
        session_id: str, payload: RecipeFilename,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.review_recipe_save(
            session_id, expected_revision, payload.filename,
        ))

    @router.post("/save/commit", dependencies=[Depends(require_web_mutation)])
    def commit_save(
        session_id: str, payload: SaveToken,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.commit_recipe_save(
            session_id, expected_revision, payload.token,
            payload.confirmed_overwrite,
        ))

    @router.post("/read/review", dependencies=[Depends(require_web_mutation)])
    def review_read(
        session_id: str, payload: RecipeFilename,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.review_recipe_read(
            session_id, expected_revision, payload.filename,
        ))

    @router.post("/read/commit", dependencies=[Depends(require_web_mutation)])
    def commit_read(
        session_id: str, payload: ReadToken,
        expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.commit_recipe_read(
            session_id, expected_revision, payload.token,
            payload.confirmed_replace,
        ))

    @router.post("/cancel", dependencies=[Depends(require_web_mutation)])
    def cancel_review(
        session_id: str, expected_revision: int = Query(..., ge=0),
    ):
        return _call(lambda: service.cancel_recipe_review(
            session_id, expected_revision,
        ))

    return router
