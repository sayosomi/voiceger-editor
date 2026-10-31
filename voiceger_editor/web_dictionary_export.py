"""Authenticated, non-destructive Web dictionary export using canonical core writers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import secrets

from .dictionary_export import (
    export_voiceger_editor_dictionaries,
    export_voicevox_dictionary,
)
from .web_recipe import WebRecipeValidation, _check_root_path, _open_root


class WebDictionaryExportValidation(ValueError):
    CODES = frozenset({
        "invalid_export", "review_expired", "export_io",
        "pitch_loss_confirmation_required",
    })

    def __init__(self, code: str) -> None:
        if code not in self.CODES:
            raise ValueError("Unknown dictionary export code")
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _ExportReview:
    token: str
    kind: str
    revision: str
    lossy_count: int


class WebDictionaryExportMixin:
    """One-use review/commit transactions; no browser paths or Take changes."""

    def _export_guard(self, session_id: str, expected_revision: str):
        from .web_sessions import WebSessionConflict

        session = self._session(session_id)
        if self._active is not None:
            raise WebSessionConflict("Audio worker is active", code="worker_busy")
        core = self._dictionary()
        if self._dictionary_version(core) != expected_revision:
            raise WebSessionConflict("Dictionary changed", code="revision_conflict")
        return session, core

    def review_dictionary_export(
        self, session_id: str, kind: str, expected_revision: str,
    ) -> dict:
        with self._lock:
            session, core = self._export_guard(session_id, expected_revision)
            if kind not in {"native", "voicevox"}:
                raise WebDictionaryExportValidation("invalid_export")
            count = (
                len(core.list_japanese_pitch_events()) if kind == "voicevox" else 0
            )
            review = _ExportReview(
                token=secrets.token_urlsafe(24),
                kind=kind,
                revision=expected_revision,
                lossy_count=count,
            )
            session.pending_dictionary_export = review
            return {
                "token": review.token, "format": kind,
                "lossy_pitch_count": count, "scope": "Mac Output folder",
            }

    def cancel_dictionary_export(self, session_id: str, token: str) -> dict:
        with self._lock:
            session = self._session(session_id)
            review = session.pending_dictionary_export
            if review is None or not secrets.compare_digest(review.token, token):
                raise WebDictionaryExportValidation("review_expired")
            session.pending_dictionary_export = None
            return {"cancelled": True}

    def commit_dictionary_export(
        self, session_id: str, token: str, expected_revision: str,
        confirmed_pitch_loss: bool,
    ) -> dict:
        with self._lock:
            session = self._session(session_id)
            review = session.pending_dictionary_export
            if review is None or not secrets.compare_digest(review.token, token):
                raise WebDictionaryExportValidation("review_expired")
            # Consume BEFORE writing, even on a failed confirmation or IO.
            session.pending_dictionary_export = None
            if review.revision != expected_revision:
                raise WebDictionaryExportValidation("review_expired")
            _, core = self._export_guard(session_id, expected_revision)
            count = len(core.list_japanese_pitch_events()) if review.kind == "voicevox" else 0
            if count != review.lossy_count:
                raise WebDictionaryExportValidation("review_expired")
            if count and confirmed_pitch_loss is not True:
                raise WebDictionaryExportValidation("pitch_loss_confirmation_required")
            try:
                root = self._recipe_root()
                # The Output directory must be a real directory at use time.
                with _open_root(root, create=True) as (_fd, identity):
                    _check_root_path(root, identity)
                    if review.kind == "native":
                        result = export_voiceger_editor_dictionaries(core, root)
                    else:
                        result = export_voicevox_dictionary(core, root)
                    _check_root_path(root, identity)
            except (OSError, ValueError, WebRecipeValidation):
                raise WebDictionaryExportValidation("export_io") from None
            except Exception:
                raise WebDictionaryExportValidation("export_io") from None
            return {
                "saved": True, "format": review.kind,
                "filename": Path(result.paths[0]).name,
                "lossy_pitch_count": len(result.lossy_pitch_event_uuids),
                "scope": "Mac Output folder",
            }
