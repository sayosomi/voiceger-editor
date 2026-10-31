"""Session-scoped selective dictionary merge, using the shared TUI-neutral core."""

from __future__ import annotations

from dataclasses import dataclass
import os
import secrets
import stat

from .dictionary_backup import DictionaryBackupReview
from .dictionary_import import DictionaryImportError
from .user_dictionary import JapaneseWordType
from .web_dictionary_import_source import (
    MAX_SOURCE_BYTES, WebDictionaryImportValidation, allowed_filename,
    plan_from_bytes, read_source, review_payload,
)
from .web_recipe import WebRecipeValidation, _check_root_path, _open_root


@dataclass
class PendingDictionaryImport:
    token: str
    filename: str
    revision: str
    fingerprint: tuple
    review: object


class WebDictionaryImportMixin:
    """Server owns the snapshot, token, selection, and atomic merge."""

    def list_dictionary_import_files(self, session_id: str) -> dict:
        with self._lock:
            self._session(session_id)
            root = self._recipe_root()
            if not root.exists() and not root.is_symlink():
                return {"files": []}
            try:
                with _open_root(root) as (directory, root_identity):
                    names = []
                    for entry in os.listdir(directory):
                        try:
                            allowed_filename(entry)
                            if entry.endswith(".voiceger.json"):
                                continue
                            info = os.stat(entry, dir_fd=directory, follow_symlinks=False)
                        except (WebDictionaryImportValidation, OSError):
                            continue
                        if stat.S_ISREG(info.st_mode) and info.st_size <= MAX_SOURCE_BYTES:
                            names.append(entry)
                    _check_root_path(root, root_identity)
                return {"files": sorted(names, reverse=True)[:200]}
            except (OSError, WebRecipeValidation):
                raise WebDictionaryImportValidation("import_io") from None

    def _require_import(self, session_id: str, token: str):
        session = self._session(session_id)
        state = session.pending_dictionary_import
        if state is None or not isinstance(token, str) or not secrets.compare_digest(
            state.token, token
        ):
            raise WebDictionaryImportValidation("review_expired")
        self._export_guard(session_id, state.revision)
        return session, state

    def review_dictionary_import(self, session_id: str, filename: str, revision: str):
        with self._lock:
            session, core = self._export_guard(session_id, revision)
            session.pending_dictionary_import = None
            allowed_filename(filename)
            root = self._recipe_root()
            try:
                with _open_root(root) as (directory, root_identity):
                    data, fingerprint = read_source(directory, filename)
                    _check_root_path(root, root_identity)
                planned = plan_from_bytes(filename, data, core)
            except DictionaryImportError:
                raise WebDictionaryImportValidation("invalid_import") from None
            except (OSError, WebRecipeValidation):
                raise WebDictionaryImportValidation("import_io") from None
            state = PendingDictionaryImport(
                secrets.token_urlsafe(24), filename, revision, fingerprint, planned,
            )
            session.pending_dictionary_import = state
            return review_payload(state, core)

    def select_dictionary_import(
        self, session_id: str, token: str, language: str,
        identity: str, selected: bool,
    ):
        with self._lock:
            _, state = self._require_import(session_id, token)
            review = state.review
            try:
                if isinstance(review, DictionaryBackupReview):
                    review.set_selected(identity, selected, language=language)
                elif (review.format.value == "japanese" and language == "ja") or (
                    review.format.value == "english" and language == "en"
                ):
                    review.set_selected(identity, selected)
                else:
                    raise WebDictionaryImportValidation("invalid_import")
            except (DictionaryImportError, ValueError):
                raise WebDictionaryImportValidation("invalid_import") from None
            return review_payload(state, self._dictionary())

    def clear_dictionary_import_selection(self, session_id: str, token: str):
        with self._lock:
            _, state = self._require_import(session_id, token)
            review = state.review
            try:
                for item in tuple(review.items):
                    if hasattr(item, "source_uuid"):
                        identity, language = item.source_uuid, "ja"
                    else:
                        identity, language = item.incoming.surface, "en"
                    if isinstance(review, DictionaryBackupReview):
                        review.set_selected(identity, False, language=language)
                    else:
                        review.set_selected(identity, False)
            except DictionaryImportError:
                raise WebDictionaryImportValidation("invalid_import") from None
            return review_payload(state, self._dictionary())

    def set_dictionary_import_word_type(
        self, session_id: str, token: str, identity: str, word_type: str,
    ):
        with self._lock:
            _, state = self._require_import(session_id, token)
            try:
                state.review.set_word_type(identity, JapaneseWordType(word_type))
            except (DictionaryImportError, AttributeError, ValueError):
                raise WebDictionaryImportValidation("invalid_import") from None
            return review_payload(state, self._dictionary())

    def cancel_dictionary_import(self, session_id: str, token: str):
        with self._lock:
            session = self._session(session_id)
            state = session.pending_dictionary_import
            if state is None or not isinstance(token, str) or not secrets.compare_digest(
                state.token, token
            ):
                raise WebDictionaryImportValidation("review_expired")
            session.pending_dictionary_import = None
            return {"cancelled": True}

    def commit_dictionary_import(self, session_id: str, token: str, confirmed: bool):
        with self._lock:
            session, state = self._require_import(session_id, token)
            # Never allow a retry to apply the same review twice.
            session.pending_dictionary_import = None
            core = self._dictionary()
            summary = review_payload(state, core)
            if not confirmed or summary["selected"] == 0:
                raise WebDictionaryImportValidation("confirmation_required")
            try:
                root = self._recipe_root()
                with _open_root(root) as (directory, root_identity):
                    _, latest = read_source(directory, state.filename)
                    _check_root_path(root, root_identity)
                if latest != state.fingerprint:
                    raise WebDictionaryImportValidation("source_changed")
                result = state.review.commit(core)
            except WebDictionaryImportValidation:
                raise
            except DictionaryImportError:
                raise WebDictionaryImportValidation("source_changed") from None
            except (OSError, WebRecipeValidation):
                raise WebDictionaryImportValidation("import_io") from None
            return {
                "imported": result.imported,
                "replaced": result.replaced,
                "skipped": result.skipped,
            }
