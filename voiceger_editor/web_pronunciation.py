"""Pure-Japanese Web pronunciation actions over shared query/session owners."""

from __future__ import annotations

import secrets

from .query_editing import (
    japanese_preview_query,
    japanese_pronunciation,
    replace_japanese_pronunciation,
)
from .voicevox_api_models import AudioQuery
from .web_takes import WebTakeValidation, _wav_bytes


MAX_PRONUNCIATION_CHARS = 2000


class WebPronunciationValidation(WebTakeValidation):
    """An invalid or unsupported, client-provided pronunciation draft."""

    def __init__(self, code: str) -> None:
        if code not in {"invalid_pronunciation", "unsupported_pronunciation"}:
            raise ValueError("Unknown pronunciation validation code")
        self.code = code
        super().__init__(code)


def prepared_japanese_notation(item) -> str | None:
    """Read only a prepared pure-Japanese query; never guess from Caption."""
    if not item.session.is_prepared:
        return None
    query = getattr(item.session, "query", None)
    if not isinstance(query, AudioQuery) or query.voicegerSegments is not None:
        return None
    # TUI shows spaces, not the core's slash separator, in editable drafts.
    return japanese_pronunciation(query).replace("/", " ")


def _draft_query(item, notation: str) -> tuple[AudioQuery, AudioQuery]:
    if not item.session.is_prepared:
        raise WebPronunciationValidation("unsupported_pronunciation")
    current = item.session.query
    if not isinstance(current, AudioQuery) or current.voicegerSegments is not None:
        raise WebPronunciationValidation("unsupported_pronunciation")
    if (
        not isinstance(notation, str)
        or not notation
        or len(notation) > MAX_PRONUNCIATION_CHARS
        or "/" in notation
        or "\n" in notation
        or "\r" in notation
    ):
        raise WebPronunciationValidation("invalid_pronunciation")
    canonical = notation.replace("　", "/").replace(" ", "/")
    try:
        updated = replace_japanese_pronunciation(current, canonical)
    except (ValueError, TypeError):
        raise WebPronunciationValidation("invalid_pronunciation") from None
    return current, updated


class WebPronunciationMixin:
    """Guarded edit actions. Synthesis stays on the existing single worker."""

    def start_japanese_draft_preview(
        self, session_id: str, item_id: str, revision: int, notation: str,
    ) -> dict:
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            self._require_terms()
            _draft_query(item, notation)
            # Shared core validates and isolates a transient pure-Japanese query.
            preview_query = japanese_preview_query(item.session.query,
                notation.replace("　", "/").replace(" ", "/"))

            # Stage bytes privately. Publish only in the worker's terminal
            # callback, under the *same lock* that resolves cancellation and
            # sets the final operation status (see WebTakeMixin._run_take_work).
            staged: tuple[str, bytes] | None = None

            def work(operation):
                nonlocal staged
                if operation.cancellation.is_set():
                    return {}
                result = item.session.preview_synthesis(preview_query)
                data = _wav_bytes(result["audio"], int(result["sampling_rate"]))
                handle = secrets.token_urlsafe(18)
                staged = (handle, data)
                return {"preview_id": handle}

            def on_terminal(status: str) -> None:
                nonlocal staged
                if status == "succeeded" and staged is not None:
                    handle, data = staged
                    session.preview_audio = (item_id, handle, data)
                    # This callback and terminal operation state are atomic.
                    operation = session.operations.get(
                        self._active[1]) if self._active is not None else None
                    if operation is not None:
                        operation.completed = 1
                staged = None

            return self._start_take_work(
                session_id, session, kind="pronunciation-preview", total=1, run=work,
                on_terminal=on_terminal,
            )

    def apply_japanese_pronunciation(
        self, session_id: str, item_id: str, revision: int, notation: str,
    ) -> dict:
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            current, updated = _draft_query(item, notation)
            # Compare semantic query data, not user-entered whitespace or
            # canonical punctuation spelling. A no-op must preserve Takes.
            if updated.model_dump() == current.model_dump():
                return {"changed": False, "batch": self._batch_snapshot(session)}
            item.session.replace_query(updated)
            item.clear_acceptance()
            item.clear_generation_outcome()
            session.preview_audio = None
            session.revision += 1
            return {"changed": True, "batch": self._batch_snapshot(session)}
