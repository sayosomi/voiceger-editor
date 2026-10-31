"""Persistent Web dictionary operations reusing the application dictionary core."""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from .dictionary_editing import (
    _english_preview_query, _japanese_preview_query, _reading_morae,
    _word_type_for_context, japanese_word_notation, parse_japanese_word,
)
from .dictionary_listing import DictionaryListStateOwner
from .openjtalk_dictionary import normalize_surface
from .english_stress import normalize_english_phonemes
from .pronunciation import format_pronunciation
from .user_dictionary import JapaneseWordType, UserDictionaryCore
from .web_takes import _wav_bytes


class WebDictionaryValidation(ValueError):
    def __init__(self, code: str = "invalid_dictionary") -> None:
        super().__init__(code)
        self.code = code


class WebDictionaryMixin:
    """Web coordination; UserDictionaryCore alone owns disk state."""

    def _dictionary(self) -> UserDictionaryCore:
        if self._dictionary_core is not None:
            return self._dictionary_core
        if self._batch_adapter is None:
            from .voiceger_adapter import VoicegerAdapter
            self._batch_adapter = VoicegerAdapter()
        return self._batch_adapter.user_dictionary

    def _dictionary_adapter(self):
        if self._batch_adapter is None:
            from .voiceger_adapter import VoicegerAdapter
            self._batch_adapter = VoicegerAdapter()
        return self._batch_adapter

    @staticmethod
    def _dictionary_version(core) -> str:
        japanese, english, events = core.native_dictionary_backup_snapshot()
        data = {
            "ja": [(key, word.model_dump(mode="json")) for key, word in japanese.items()],
            "en": [(key, word.model_dump(mode="json")) for key, word in english.items()],
            "events": sorted((key, [(e.after_mora, e.symbol) for e in value])
                             for key, value in events.items()),
        }
        return hashlib.sha256(json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()

    @staticmethod
    def _language(value: str) -> str:
        if value not in ("ja", "en"):
            raise WebDictionaryValidation()
        return value

    def _dictionary_entries(self, core, language, sort, query, word_type):
        state = DictionaryListStateOwner(core)
        try:
            if language == "ja":
                state.set_japanese_sort(sort)
                state.set_japanese_filter(text_query=query, word_type_filter=word_type)
                view = state.japanese_view()
                pitch = core.list_japanese_pitch_events()
                rows = [{
                    "id": key, "surface": word.surface,
                    "notation": japanese_word_notation(word, pitch.get(key, ())),
                    "word_type": _word_type_for_context(word.context_id).value,
                    "priority": word.priority,
                } for key, word in view.entries]
            else:
                state.set_english_sort(sort)
                state.set_english_filter(text_query=query)
                view = state.english_view()
                rows = [{
                    "id": word.surface, "surface": word.surface,
                    "notation": " ".join(word.phonemes),
                } for word in view.entries]
        except (ValueError, TypeError) as exc:
            raise WebDictionaryValidation() from exc
        return {"entries": rows, "total": view.total_count, "shown": view.shown_count}

    def dictionary_matching_words(self, session_id, language, surface):
        """Exact identity candidates from the canonical Core, never browser guesses."""
        with self._lock:
            self._session(session_id)
            language = self._language(language)
            if not isinstance(surface, str) or not surface.strip() or len(surface) > 2000:
                raise WebDictionaryValidation()
            core = self._dictionary()
            if language == "ja":
                key = normalize_surface(surface)
                matches = [
                    {"id": uid, "surface": word.surface,
                     "word_type": _word_type_for_context(word.context_id).value,
                     "priority": word.priority}
                    for uid, word in core.list_japanese_entries().items()
                    if word.surface == key
                ]
            else:
                key = surface.strip().casefold()
                matches = [
                    {"id": word.surface, "surface": word.surface}
                    for word in core.list_english_entries().values()
                    if word.surface.strip().casefold() == key
                ]
            return {"entries": matches, "revision": self._dictionary_version(core)}

    def list_dictionary(self, session_id, language, sort, query="", word_type="ALL"):
        with self._lock:
            self._session(session_id)
            language = self._language(language)
            core = self._dictionary()
            result = self._dictionary_entries(core, language, sort, query, word_type)
            return {"revision": self._dictionary_version(core), **result}

    def _dictionary_guard(self, session_id, expected_revision):
        from .web_sessions import WebSessionConflict
        session = self._session(session_id)
        if self._active is not None:
            raise WebSessionConflict("One operation is already running", code="worker_busy")
        core = self._dictionary()
        if (not isinstance(expected_revision, str) or
                self._dictionary_version(core) != expected_revision):
            raise WebSessionConflict("Dictionary changed; reload", code="revision_conflict")
        return session, core

    @staticmethod
    def _resolve_word(core, language, identity):
        if language == "ja":
            return core.list_japanese_entries().get(identity)
        for entry in core.list_english_entries().values():
            if entry.surface.strip().casefold() == identity.strip().casefold():
                return entry
        return None

    def save_dictionary_word(self, session_id, payload, word_id=None):
        from .web_sessions import WebSessionConflict
        with self._lock:
            session, core = self._dictionary_guard(session_id, payload.expected_revision)
            language = self._language(payload.language)
            surface = payload.surface
            if not isinstance(surface, str) or not surface.strip():
                raise WebDictionaryValidation()
            original = self._resolve_word(core, language, word_id) if word_id else None
            if word_id is not None and original is None:
                raise WebSessionConflict("Dictionary word changed", code="revision_conflict")
            try:
                if language == "ja":
                    existing_events = core.get_japanese_pitch_events(word_id) if original else ()
                    opening = japanese_word_notation(original, existing_events) if original else None
                    reading, accent, events = parse_japanese_word(
                        payload.notation, opening=opening, existing=original,
                        pitch_events=existing_events,
                    )
                    kind = JapaneseWordType(payload.word_type)
                    priority = payload.priority
                    if type(priority) is not int or not 0 <= priority <= 10:
                        raise ValueError("priority outside 0..10")
                    if original and (original.surface == surface and
                        original.pronunciation == reading and
                        original.accent_type == accent and
                        tuple(existing_events) == tuple(events) and
                        _word_type_for_context(original.context_id) == kind and
                        original.priority == priority):
                        return {"changed": False, "id": word_id,
                                "revision": self._dictionary_version(core)}
                    if original:
                        core.update_japanese_word(word_id, surface=surface,
                            pronunciation=reading, accent_type=accent, pitch_events=events,
                            word_type=kind, priority=priority)
                        identity = word_id
                    else:
                        identity = core.add_japanese_word(surface=surface,
                            pronunciation=reading, accent_type=accent, pitch_events=events,
                            word_type=kind, priority=priority)
                else:
                    phones = normalize_english_phonemes(payload.notation.split())
                    if original and original.surface == surface and list(original.phonemes) == phones:
                        return {"changed": False, "id": original.surface,
                                "revision": self._dictionary_version(core)}
                    if original:
                        core.update_english_entry(original.surface, surface=surface, phonemes=phones)
                    else:
                        if core.lookup_english_entry(surface) is not None:
                            raise ValueError("English dictionary word already exists")
                        core.add_english_entry(surface, phones)
                    identity = surface
            except (ValueError, TypeError) as exc:
                raise WebDictionaryValidation() from exc
            return {"changed": True, "id": identity,
                    "revision": self._dictionary_version(core)}

    def delete_dictionary_word(self, session_id, language, word_id, expected_revision):
        from .web_sessions import WebSessionConflict
        with self._lock:
            session, core = self._dictionary_guard(session_id, expected_revision)
            language = self._language(language)
            if self._resolve_word(core, language, word_id) is None:
                raise WebSessionConflict("Dictionary word changed", code="revision_conflict")
            try:
                if language == "ja":
                    core.delete_japanese_word(word_id)
                else:
                    core.delete_english_entry(word_id)
            except (ValueError, TypeError) as exc:
                raise WebDictionaryValidation() from exc
            return {"deleted": True, "revision": self._dictionary_version(core)}

    def validate_dictionary_pronunciation(
        self, session_id, language, surface, notation,
    ):
        """Validate the exact draft using shared dictionary rules; never persist."""
        with self._lock:
            self._session(session_id)
            language = self._language(language)
            if (not isinstance(surface, str) or not surface.strip()
                    or len(surface) > 2000):
                raise WebDictionaryValidation()
            try:
                if language == "ja":
                    parse_japanese_word(notation)
                else:
                    normalize_english_phonemes(notation.split())
            except (ValueError, TypeError, AttributeError) as exc:
                raise WebDictionaryValidation() from exc
            return {"valid": True}

    def start_dictionary_generate(self, session_id, language, surface):
        from .web_sessions import WebSessionConflict
        with self._lock:
            session = self._session(session_id)
            if self._active is not None:
                raise WebSessionConflict("Worker busy", code="worker_busy")
            self._language(language)
            if not isinstance(surface, str) or not surface.strip() or len(surface) > 2000:
                raise WebDictionaryValidation()
            adapter = self._dictionary_adapter()

            def work(op):
                if op.cancellation.is_set():
                    return {}
                if language == "ja":
                    pronunciation = adapter.japanese_dictionary_pronunciation(surface)
                    if len(pronunciation.phrases) != 1:
                        raise ValueError("One dictionary phrase required")
                    notation = format_pronunciation(pronunciation)
                else:
                    groups = adapter.english_word_phoneme_groups(surface)
                    if len(groups) != 1:
                        raise ValueError("One dictionary word required")
                    notation = " ".join(normalize_english_phonemes(groups[0][1]))
                op.completed = 1
                return {"notation": notation}
            return self._start_take_work(
                session_id, session, kind="dictionary-generate", total=1, run=work)

    def start_dictionary_preview(self, session_id, language, surface, notation):
        from .web_sessions import WebSessionConflict
        with self._lock:
            session = self._session(session_id)
            if self._active is not None:
                raise WebSessionConflict("Worker busy", code="worker_busy")
            self._language(language)
            self._require_terms()
            if (not isinstance(surface, str) or not surface.strip()
                    or len(surface) > 2000):
                raise WebDictionaryValidation()
            try:
                if language == "ja":
                    reading, accent, events = parse_japanese_word(notation)
                    query = _japanese_preview_query(_reading_morae(reading), accent, events)
                else:
                    query = _english_preview_query(surface, notation.split())
            except (ValueError, TypeError) as exc:
                raise WebDictionaryValidation() from exc
            staged = None
            adapter = (None if self._dictionary_preview_provider is not None
                       else self._dictionary_adapter())

            def work(op):
                nonlocal staged
                if op.cancellation.is_set():
                    return {}
                if self._dictionary_preview_provider is not None:
                    result = self._dictionary_preview_provider(surface, query)
                else:
                    from .session import UtteranceSession
                    from .settings import load_settings
                    if self._batch_settings is None:
                        self._batch_settings = load_settings()
                    draft = UtteranceSession(adapter=adapter, caption=surface,
                        query=query, settings=self._batch_settings)
                    result = draft.preview_synthesis(query)
                wav = _wav_bytes(result["audio"], int(result["sampling_rate"]))
                handle = secrets.token_urlsafe(18)
                staged = (handle, wav)
                op.completed = 1
                return {"preview_id": handle}

            def finish(status):
                if status == "succeeded" and staged is not None:
                    session.preview_audio = ("dictionary", staged[0], staged[1])
                else:
                    session.preview_audio = None

            return self._start_take_work(session_id, session,
                kind="dictionary-preview", total=1, run=work, on_terminal=finish)

    def dictionary_preview_bytes(self, session_id, handle):
        from .web_sessions import WebSessionNotFound
        with self._lock:
            session = self._session(session_id)
            stored = session.preview_audio
            if stored is None or stored[0] != "dictionary" or stored[1] != handle:
                raise WebSessionNotFound("Dictionary Preview not found")
            return stored[2]
