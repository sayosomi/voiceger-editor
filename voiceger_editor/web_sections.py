"""Guarded Web spoken-section changes over shared canonical AudioQuery helpers."""

from __future__ import annotations

from .query_editing import (
    append_english_section,
    append_japanese_section,
    delete_utterance_section,
    english_section_text_preview_query,
    japanese_section_text_preview_query,
    merge_english_section_text_groups,
    replace_english_section_text,
    replace_japanese_section_text,
)
from .voicevox_api_models import AudioQuery
from .web_english import EnglishGroups
from .web_pronunciation import WebPronunciationValidation


def _valid_text(text: str) -> None:
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise WebPronunciationValidation("invalid_section_text")
    if "\n" in text or "\r" in text or any(ord(c) < 32 for c in text):
        raise WebPronunciationValidation("invalid_section_text")


def _valid_language(language: str) -> None:
    if language not in ("ja", "en"):
        raise WebPronunciationValidation("invalid_section")


class WebSectionMixin:
    """Single-section rebuild, append and delete; preserve Caption and saved files."""

    @staticmethod
    def _section(query: AudioQuery, index: int | None, language: str,
                 opening: str | None) -> None:
        _valid_language(language)
        if query.voicegerSegments is None:
            if index is not None or language != "ja":
                raise WebPronunciationValidation("invalid_section")
            return
        segments = query.voicegerSegments
        if type(index) is not int or not 0 <= index < len(segments):
            raise WebPronunciationValidation("invalid_section")
        segment = segments[index]
        if segment.language != language:
            raise WebPronunciationValidation("stale_section")
        if opening is not None and segment.text != opening:
            raise WebPronunciationValidation("stale_section")

    def _section_query(self, session, item):
        if not item.session.is_prepared or not isinstance(item.session.query, AudioQuery):
            raise WebPronunciationValidation("invalid_section")
        return item.session.query

    def _section_groups(self, item, text: str):
        provider = self._english_group_provider
        if provider is None:
            adapter = getattr(item.session, "_adapter", None) or self._batch_adapter
            provider = getattr(adapter, "english_word_phoneme_groups", None)
        if provider is None:
            raise WebPronunciationValidation("grouping_unavailable")
        try:
            groups = tuple((label, tuple(phones)) for label, phones in provider(text))
            if not groups:
                raise ValueError("no word groups")
            return groups
        except Exception:
            raise WebPronunciationValidation("grouping_unavailable") from None

    def _section_text_draft(self, session, item, language, index, opening, text,
                            *, preview=False):
        query = self._section_query(session, item)
        _valid_text(text)
        self._section(query, index, language, opening)
        original = (item.session.pure_japanese_utterance_text
                    if index is None else query.voicegerSegments[index].text)
        if original is None or original != opening:
            raise WebPronunciationValidation("stale_section")
        updated_groups = None
        try:
            if language == "ja":
                if preview:
                    updated = japanese_section_text_preview_query(
                        query, text, segment_index=index)
                else:
                    updated = replace_japanese_section_text(
                        query, text, segment_index=index)
            else:
                existing = self._english_grouping(session, item, query, index)
                old_groups = existing.groups
                generated = self._section_groups(item, text)
                updated_groups = merge_english_section_text_groups(
                    query, segment_index=index, old_groups=old_groups,
                    new_groups=generated)
                if preview:
                    updated = english_section_text_preview_query(
                        query, segment_index=index, text=text,
                        old_groups=old_groups, new_groups=generated)
                else:
                    updated = replace_english_section_text(
                        query, segment_index=index, text=text,
                        phoneme_groups=updated_groups)
        except WebPronunciationValidation:
            raise
        except (ValueError, TypeError):
            raise WebPronunciationValidation("invalid_section_text") from None
        return query, updated, updated_groups

    @staticmethod
    def _commit_section(session, item, updated, *, pure_text=None):
        item.session.replace_query(
            updated, pure_japanese_utterance_text=pure_text)
        item.clear_acceptance()
        item.clear_generation_outcome()
        session.preview_audio = None
        session.revision += 1

    def start_section_text_preview(self, session_id, item_id, revision,
                                   language, index, opening, text):
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            self._require_terms()
            _, preview, _ = self._section_text_draft(
                session, item, language, index, opening, text, preview=True)
            return self._start_pronunciation_preview(
                session_id, session, item, item_id, preview)

    def apply_section_text(self, session_id, item_id, revision,
                           language, index, opening, text):
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            query, updated, groups = self._section_text_draft(
                session, item, language, index, opening, text)
            if updated.model_dump() == query.model_dump():
                return {"changed": False, "batch": self._batch_snapshot(session)}
            self._commit_section(
                session, item, updated, pure_text=text if index is None else None)
            if language == "en":
                session.english_groupings[(item_id, index)] = EnglishGroups(
                    text, tuple((label, tuple(phones)) for label, phones in groups))
            return {"changed": True, "batch": self._batch_snapshot(session)}

    def append_section(self, session_id, item_id, revision, language, text):
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            _valid_language(language)
            _valid_text(text)
            query = self._section_query(session, item)
            groups = None
            try:
                if language == "ja":
                    updated = append_japanese_section(
                        query, text,
                        pure_japanese_utterance_text=item.session.pure_japanese_utterance_text)
                else:
                    groups = self._section_groups(item, text)
                    updated = append_english_section(
                        query, text, phoneme_groups=groups,
                        pure_japanese_utterance_text=item.session.pure_japanese_utterance_text)
            except WebPronunciationValidation:
                raise
            except (ValueError, TypeError):
                raise WebPronunciationValidation("invalid_section_text") from None
            self._commit_section(session, item, updated)
            if groups is not None:
                index = len(updated.voicegerSegments) - 1
                session.english_groupings[(item_id, index)] = EnglishGroups(
                    text, tuple((label, tuple(phones)) for label, phones in groups))
            return {"changed": True, "batch": self._batch_snapshot(session)}

    def delete_section(self, session_id, item_id, revision,
                       language, index, opening):
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            query = self._section_query(session, item)
            self._section(query, index, language, opening)
            if query.voicegerSegments is None or len(query.voicegerSegments) < 2:
                raise WebPronunciationValidation("invalid_section")
            try:
                updated, pure_text = delete_utterance_section(
                    query, segment_index=index)
            except (ValueError, TypeError):
                raise WebPronunciationValidation("invalid_section") from None
            # Construct the new cache before changing the canonical query.
            remapped = {}
            for (current_item, current_index), grouped in session.english_groupings.items():
                if current_item != item_id:
                    remapped[(current_item, current_index)] = grouped
                elif current_index != index:
                    shifted = current_index - 1 if current_index > index else current_index
                    remapped[(item_id, shifted)] = grouped
            self._commit_section(session, item, updated, pure_text=pure_text)
            session.english_groupings = remapped
            return {"changed": True, "batch": self._batch_snapshot(session)}
