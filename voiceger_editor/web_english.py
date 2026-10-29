"""English word grouping and Web pronunciation edits over canonical AudioQuery."""
from __future__ import annotations

from dataclasses import dataclass

from .english_stress import normalize_english_phonemes
from .query_editing import (
    english_word_preview_query, japanese_pronunciation,
    replace_english_phoneme_groups,
)
from .voicevox_api_models import AudioQuery
from .web_pronunciation import WebPronunciationValidation, prepared_japanese_notation

PUNCTUATION = frozenset({".", ",", "!", "?", "…"})


@dataclass(frozen=True)
class EnglishGroups:
    source_text: str
    groups: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def flattened(self) -> tuple[str, ...]:
        return tuple(token for _label, phones in self.groups for token in phones)


def _is_punctuation(label: str, phones: tuple[str, ...]) -> bool:
    return bool(label) and all(c in PUNCTUATION for c in label) and (
        len(phones) == 1 and phones[0] in PUNCTUATION
    )


class WebEnglishMixin:
    """Session-owned grouping persists edited phoneme boundaries until rebuild."""

    def _english_grouping(self, session, item, query: AudioQuery, index: int) -> EnglishGroups:
        segments = query.voicegerSegments
        if segments is None or type(index) is not int or not 0 <= index < len(segments):
            raise WebPronunciationValidation("unsupported_pronunciation")
        segment = segments[index]
        if segment.language != "en" or segment.phonemes is None:
            raise WebPronunciationValidation("unsupported_pronunciation")
        canonical = tuple(segment.phonemes)
        key = (item.item_id, index)
        cached = session.english_groupings.get(key)
        if cached is not None and cached.source_text == segment.text and cached.flattened == canonical:
            return cached
        session.english_groupings.pop(key, None)
        provider = self._english_group_provider
        if provider is None:
            adapter = getattr(item.session, "_adapter", None) or self._batch_adapter
            provider = getattr(adapter, "english_word_phoneme_groups", None)
        if provider is None:
            raise WebPronunciationValidation("grouping_unavailable")
        try:
            raw = provider(segment.text)
            groups = tuple((label, tuple(phones)) for label, phones in raw)
            if not groups or any(not isinstance(label, str) for label, _ in groups):
                raise ValueError("invalid word grouping")
            if any(any(not isinstance(p, str) for p in phones) for _, phones in groups):
                raise ValueError("invalid word phonemes")
            baseline = tuple(p for _, phones in groups for p in phones)
            if baseline != canonical:
                # Match TUI: only a single-token punctuation replacement may rebind.
                rebound = []
                offset = 0
                for label, phones in groups:
                    actual = canonical[offset:offset + len(phones)]
                    if len(actual) != len(phones) or (
                        actual != phones and not _is_punctuation(label, actual)
                    ):
                        raise ValueError("word grouping does not match current query")
                    rebound.append((label, actual))
                    offset += len(phones)
                if offset != len(canonical):
                    raise ValueError("unmatched English suffix")
                groups = tuple(rebound)
            if tuple(p for _, phones in groups for p in phones) != canonical:
                raise ValueError("word grouping does not match canonical phonemes")
            grouping = EnglishGroups(segment.text, groups)
        except Exception:
            raise WebPronunciationValidation("grouping_unavailable") from None
        session.english_groupings[key] = grouping
        return grouping

    def _pronunciation_sections(self, session, item) -> list[dict]:
        if not item.session.is_prepared:
            return []
        query = getattr(item.session, "query", None)
        if not isinstance(query, AudioQuery):
            return []
        if query.voicegerSegments is None:
            return [{
                "language": "ja", "index": None,
                "text": getattr(item.session, "pure_japanese_utterance_text", None)
                        or getattr(item.session, "synthesis_source_text", item.caption),
                "notation": prepared_japanese_notation(item),
            }]
        sections = []
        for index, segment in enumerate(query.voicegerSegments):
            if segment.language == "ja":
                sections.append({
                    "language": "ja", "index": index, "text": segment.text,
                    "notation": japanese_pronunciation(query, segment_index=index).replace("/", " "),
                })
            elif segment.language == "en":
                section = {"language": "en", "index": index, "text": segment.text}
                try:
                    grouping = self._english_grouping(session, item, query, index)
                    entries = []
                    for group_index, (label, phones) in enumerate(grouping.groups):
                        punctuation = _is_punctuation(label, phones)
                        editable = punctuation or any(c.isalpha() for c in label)
                        # Never silently omit an uneditable token boundary:
                        # users must see the complete canonical segment.
                        entries.append({
                            "index": group_index,
                            "label": phones[0] if punctuation else label,
                            "notation": " ".join(phones),
                            "display": " ".join(
                                "[" + p + "]" if p.endswith("1") and p[:-1].isalpha() else p
                                for p in phones
                            ),
                            "punctuation": punctuation,
                            "editable": editable,
                        })
                    section["groups"] = entries
                except WebPronunciationValidation:
                    section["error"] = "grouping_unavailable"
                sections.append(section)
        return sections

    def _english_draft(self, session, item, segment_index: int, group_index: int,
                       opening: str, notation: str):
        if not item.session.is_prepared:
            raise WebPronunciationValidation("unsupported_pronunciation")
        query = item.session.query
        if not isinstance(query, AudioQuery):
            raise WebPronunciationValidation("unsupported_pronunciation")
        grouping = self._english_grouping(session, item, query, segment_index)
        if type(group_index) is not int or not 0 <= group_index < len(grouping.groups):
            raise WebPronunciationValidation("unsupported_pronunciation")
        label, phones = grouping.groups[group_index]
        if not (_is_punctuation(label, phones) or any(c.isalpha() for c in label)):
            raise WebPronunciationValidation("unsupported_pronunciation")
        if not isinstance(opening, str) or opening != " ".join(phones):
            raise WebPronunciationValidation("stale_pronunciation")
        if (not isinstance(notation, str) or not notation.strip()
                or len(notation) > 2000 or "\n" in notation or "\r" in notation):
            raise WebPronunciationValidation("invalid_english_pronunciation")
        try:
            draft = tuple(normalize_english_phonemes(notation.split()))
        except (ValueError, TypeError):
            raise WebPronunciationValidation("invalid_english_pronunciation") from None
        if _is_punctuation(label, phones) and not (
            len(draft) == 1 and draft[0] in PUNCTUATION
        ):
            raise WebPronunciationValidation("invalid_english_pronunciation")
        groups = tuple(group for _label, group in grouping.groups)
        return query, grouping, draft, groups

    def start_english_draft_preview(self, session_id: str, item_id: str,
                                    revision: int, segment_index: int, group_index: int,
                                    opening: str, notation: str) -> dict:
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            self._require_terms()
            query, _grouping, draft, groups = self._english_draft(
                session, item, segment_index, group_index, opening, notation
            )
            try:
                preview = english_word_preview_query(
                    query, segment_index=segment_index, group_index=group_index,
                    phoneme_groups=groups, draft_phonemes=draft,
                )
            except (ValueError, TypeError):
                raise WebPronunciationValidation("invalid_english_pronunciation") from None
            return self._start_pronunciation_preview(session_id, session, item, item_id, preview)

    def apply_english_pronunciation(self, session_id: str, item_id: str, revision: int,
                                    segment_index: int, group_index: int,
                                    opening: str, notation: str) -> dict:
        with self._lock:
            session, item = self._take_guard(session_id, item_id, revision)
            query, grouping, draft, groups = self._english_draft(
                session, item, segment_index, group_index, opening, notation
            )
            replacement_groups = list(groups)
            replacement_groups[group_index] = draft
            try:
                updated = replace_english_phoneme_groups(
                    query, segment_index=segment_index, phoneme_groups=replacement_groups
                )
            except (ValueError, TypeError):
                raise WebPronunciationValidation("invalid_english_pronunciation") from None
            if updated.model_dump() == query.model_dump():
                return {"changed": False, "batch": self._batch_snapshot(session)}
            new_groups = list(grouping.groups)
            new_groups[group_index] = (new_groups[group_index][0], draft)
            item.session.replace_query(updated)
            session.english_groupings[(item_id, segment_index)] = EnglishGroups(
                grouping.source_text, tuple(new_groups)
            )
            item.clear_acceptance()
            item.clear_generation_outcome()
            session.preview_audio = None
            session.revision += 1
            return {"changed": True, "batch": self._batch_snapshot(session)}
