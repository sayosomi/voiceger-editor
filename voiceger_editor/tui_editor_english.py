"""English grouping cache and stress-editing ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

from .english_stress import (
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
)
from .query_editing import move_english_primary_stress
from .tui_editor_common import (
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    EditorOwnerBase,
    ReplaceQueryIntent,
    UpdateStatusIntent,
)
from .tui_status import Status, error_status
from .voicevox_api_models import AudioQuery


@dataclass(frozen=True)
class EnglishWordGroup:
    """A source word and its editable or fixed ARPAbet token group."""

    label: str
    phonemes: tuple[str, ...]
    editable: bool


@dataclass(frozen=True)
class EnglishGroupingCache:
    source_text: str
    groups: tuple[EnglishWordGroup, ...]

    @property
    def flattened(self) -> tuple[str, ...]:
        return tuple(phone for group in self.groups for phone in group.phonemes)


class TuiEnglishEditorOwner(EditorOwnerBase):
    """Own English grouping snapshots and Main stress adjustment policy."""

    def __init__(
        self,
        host,
        *,
        english_word_groups: Callable[[str], Sequence[tuple[str, Sequence[str]]]],
    ) -> None:
        super().__init__(host)
        self._english_word_groups = english_word_groups
        self.grouping_cache: dict[int, EnglishGroupingCache] = {}
        self.grouping_error: Status | None = None

    def english_grouping(
        self,
        query: AudioQuery,
        segment_index: int,
    ) -> EnglishGroupingCache:
        if query.voicegerSegments is None:
            raise ValueError("English word editing requires a mixed-language segment")
        if not 0 <= segment_index < len(query.voicegerSegments):
            raise ValueError("English segment index is out of range")
        segment = query.voicegerSegments[segment_index]
        if segment.language != "en" or segment.phonemes is None:
            raise ValueError("selected segment is not an editable English segment")
        canonical_flat = tuple(segment.phonemes)
        cached = self.grouping_cache.get(segment_index)
        if (
            cached is not None
            and cached.source_text == segment.text
            and cached.flattened == canonical_flat
        ):
            return cached
        self.grouping_cache.pop(segment_index, None)

        raw_groups = self._english_word_groups(segment.text)
        groups = tuple(
            EnglishWordGroup(
                label=label,
                phonemes=tuple(phonemes),
                editable=any(character.isalpha() for character in label),
            )
            for label, phonemes in raw_groups
        )
        grouped_flat = tuple(phone for group in groups for phone in group.phonemes)
        if not groups or grouped_flat != canonical_flat:
            raise ValueError(
                "Voiceger word groups do not exactly match the current English segment"
            )
        cache = EnglishGroupingCache(segment.text, groups)
        self.grouping_cache[segment_index] = cache
        return cache

    def adjust_stress(
        self,
        query: AudioQuery,
        row,
        direction: int,
    ) -> tuple[EditorIntent, ...]:
        clear = (ClearAdjustmentFeedbackIntent(),)
        try:
            if (
                row.language != "en"
                or row.model_segment_index is None
                or row.group_index is None
                or row.grouping is None
            ):
                return clear

            group = row.grouping.groups[row.group_index]
            state = english_phonemes_to_editor_state(group.phonemes)
            primary_positions = state.primary_stress_vowel_positions
            if direction not in {-1, 1} or len(primary_positions) != 1:
                return clear
            source = primary_positions[0]
            target = source + direction
            if not 0 <= target < len(state.vowel_stresses):
                return clear
            updated = move_english_primary_stress(
                query,
                segment_index=row.model_segment_index,
                source_vowel_position=row.vowel_offset + source,
                target_vowel_position=row.vowel_offset + target,
            )
            moved_group_state = move_primary_stress(state, source, target)
            groups = list(row.grouping.groups)
            groups[row.group_index] = replace(
                group,
                phonemes=tuple(editor_state_to_english_phonemes(moved_group_state)),
            )
            accepted_grouping = EnglishGroupingCache(
                row.grouping.source_text,
                tuple(groups),
            )
            return (
                ReplaceQueryIntent(
                    query=updated,
                    editor_kind="english_word",
                    success_status="English stress updated; old takes cleared.",
                    grouping_index=row.model_segment_index,
                    accepted_grouping=accepted_grouping,
                    close_editor=False,
                ),
            )
        except Exception as exc:
            return (
                *clear,
                UpdateStatusIntent(
                    error_status(f"Pronunciation was not changed: {exc}")
                ),
            )

    def reconcile_groupings(self, query: AudioQuery) -> None:
        segments = query.voicegerSegments or []
        for index, cached in tuple(self.grouping_cache.items()):
            if (
                index >= len(segments)
                or segments[index].language != "en"
                or segments[index].text != cached.source_text
                or segments[index].phonemes is None
                or tuple(segments[index].phonemes) != cached.flattened
            ):
                self.grouping_cache.pop(index, None)

    def remap_groupings_after_deletion(
        self,
        deleted_index: int,
        query: AudioQuery,
    ) -> None:
        remapped: dict[int, EnglishGroupingCache] = {}
        for index, grouping in self.grouping_cache.items():
            if index == deleted_index:
                continue
            remapped[index if index < deleted_index else index - 1] = grouping
        self.grouping_cache = remapped
        self.reconcile_groupings(query)

    def clear_groupings(self) -> None:
        self.grouping_cache.clear()
        self.grouping_error = None
