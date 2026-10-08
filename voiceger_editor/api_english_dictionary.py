"""English user-dictionary HTTP routes backed by the shared application core."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .terms_acceptance import VoicegerTermsAcceptanceError
from .user_dictionary import (
    EnglishUserDictionaryEntry,
    UserDictionaryInputError,
)
from .voiceger_adapter import VoicegerAdapter
from .voiceger_environment import VoicegerEnvironmentError


def build_english_dictionary_router(
    get_adapter: Callable[[], VoicegerAdapter],
) -> APIRouter:
    """Keep English dictionary HTTP policy separate from the VOICEVOX API."""

    router = APIRouter()

    def run(action: Callable[[], Any], *, operation: str) -> Any:
        try:
            return action()
        except UserDictionaryInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (VoicegerEnvironmentError, VoicegerTermsAcceptanceError):
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"English user dictionary could not be {operation}.",
            ) from exc

    @router.get("/english_user_dict", response_model=dict[str, list[str]])
    def list_english_dictionary():
        """Return the native English dictionary JSON shape."""

        def read():
            entries = get_adapter().user_dictionary.list_english_entries()
            return {
                surface: list(entry.phonemes)
                for surface, entry in entries.items()
            }

        return run(read, operation="loaded")

    @router.post(
        "/english_user_dict_word",
        response_model=EnglishUserDictionaryEntry,
    )
    def set_english_dictionary_word(entry: EnglishUserDictionaryEntry):
        """Insert or replace a case-insensitively matching entry."""

        return run(
            lambda: get_adapter().user_dictionary.set_english_entry(
                entry.surface, entry.phonemes
            ),
            operation="updated",
        )

    @router.put("/english_user_dict_word/{surface}", status_code=204)
    def update_english_dictionary_word(
        surface: str, entry: EnglishUserDictionaryEntry
    ):
        """Update an existing word, allowing its surface to change."""

        run(
            lambda: get_adapter().user_dictionary.update_english_entry(
                surface,
                surface=entry.surface,
                phonemes=entry.phonemes,
            ),
            operation="updated",
        )

    @router.delete("/english_user_dict_word/{surface}", status_code=204)
    def delete_english_dictionary_word(surface: str):
        """Delete an entry by its case-insensitive surface."""

        run(
            lambda: get_adapter().user_dictionary.delete_english_entry(surface),
            operation="updated",
        )

    @router.post("/import_english_user_dict", status_code=204)
    def import_english_dictionary(
        entries: dict[str, list[str]],
        override: bool = Query(False),
    ):
        """Import native English dictionary JSON as one atomic operation."""

        run(
            lambda: get_adapter().user_dictionary.import_english(
                entries, override=override
            ),
            operation="updated",
        )

    return router
