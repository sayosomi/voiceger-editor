"""Editor state, interaction policy, and application intent boundaries."""

from __future__ import annotations

import curses
from copy import deepcopy
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Sequence, Union

from .english_stress import (
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
    normalize_english_phonemes,
)
from .query_editing import (
    append_english_section,
    append_japanese_section,
    delete_utterance_section,
    english_section_text_preview_query,
    english_word_preview_query,
    merge_english_section_text_groups,
    japanese_pronunciation,
    japanese_preview_query,
    move_english_primary_stress,
    move_japanese_accent,
    replace_english_section_text,
    replace_english_phoneme_groups,
    replace_japanese_pronunciation,
    replace_japanese_section_text,
    japanese_section_text_preview_query,
)
from .pronunciation import (
    AccentPhrase as CoreAccentPhrase,
    PronunciationPunctuation as CorePronunciationPunctuation,
    canonicalize_punctuation,
    parse_pronunciation,
)
from .settings import (
    Settings,
    SettingsError,
    VOICEGER_DEFAULT_TEMPERATURE,
    VOICEGER_DEFAULT_TOP_K,
    VOICEGER_DEFAULT_TOP_P,
)
from .tui_display import _display_width, _move_wrapped_cursor
from .tui_shortcuts import menu_items, resolve_shortcut
from .tui_status import EMPTY_STATUS, Status, error_status, info_status
from .voicevox_api_models import AudioQuery


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"

_SETTINGS_SECTIONS = (
    ("style_id", "speed"),
    ("take_count",),
    ("output_dir", "save_text", "save_lab"),
    ("top_k", "top_p", "temperature", "reset_sampling"),
    ("apply", "reset", "back"),
)


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


@dataclass(frozen=True)
class PronunciationRow:
    """One selectable Japanese AccentPhrase or aligned English word group."""

    language: str
    source_text: str
    source_segment_index: int
    model_segment_index: int | None
    first_in_segment: bool
    phrase_index: int | None = None
    phrase_index_in_segment: int | None = None
    moras: tuple[str, ...] = ()
    accent: int | None = None
    group_index: int | None = None
    word: str | None = None
    phonemes: tuple[str, ...] = ()
    vowel_offset: int = 0
    word_column_width: int = 0
    grouping: EnglishGroupingCache | None = None
    punctuation_suffix: str = ""


def _punctuation_suffixes(value: str) -> tuple[str, ...]:
    """Return canonical punctuation grouped after each phrase in notation."""

    pronunciation = parse_pronunciation(value)
    suffixes: list[str] = []
    phrase_index = -1
    for item in pronunciation.items:
        if isinstance(item, CoreAccentPhrase):
            phrase_index += 1
            suffixes.append("")
        elif isinstance(item, CorePronunciationPunctuation):
            if phrase_index < 0:
                raise ValueError(
                    "pronunciation punctuation has no preceding phrase"
                )
            suffixes[phrase_index] += item.mark
        else:
            raise ValueError(f"unsupported pronunciation item: {item!r}")
    return tuple(suffixes)


@dataclass
class EditorState:
    kind: str
    title: str
    origin: tuple[str, int | None]
    selection: str | tuple[str, int | None]
    payload: dict[str, Any] = field(default_factory=dict)
    active_field: str | None = None
    input_value: str = ""
    input_cursor: int = 0
    input_original: str = ""
    error: Status = EMPTY_STATUS
    scroll: int = 0


@dataclass(frozen=True)
class ReplaceQueryIntent:
    query: AudioQuery
    editor_kind: str
    success_status: Status
    grouping_index: int | None = None
    accepted_grouping: EnglishGroupingCache | None = None
    deleted_segment_index: int | None = None
    pure_japanese_utterance_text: str | None = None
    close_editor: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.success_status, Status):
            object.__setattr__(
                self,
                "success_status",
                info_status(str(self.success_status)),
            )


@dataclass(frozen=True)
class PreviewIntent:
    query: AudioQuery


@dataclass(frozen=True)
class ApplyCaptionIntent:
    caption: str


@dataclass(frozen=True)
class BuildPronunciationIntent:
    pass


@dataclass(frozen=True)
class ApplySettingsIntent:
    settings: Settings


@dataclass(frozen=True)
class CloseEditorIntent:
    origin: tuple[str, int | None]
    status: Status

    def __post_init__(self) -> None:
        if not isinstance(self.status, Status):
            object.__setattr__(self, "status", info_status(str(self.status)))


@dataclass(frozen=True)
class UpdateStatusIntent:
    status: Status

    def __init__(self, status: Status | str) -> None:
        object.__setattr__(
            self,
            "status",
            status if isinstance(status, Status) else info_status(status),
        )


@dataclass(frozen=True)
class AdjustmentPressedIntent:
    area: str
    control: str
    direction: int


@dataclass(frozen=True)
class ClearAdjustmentFeedbackIntent:
    pass


@dataclass(frozen=True)
class OpenHelpIntent:
    pass


@dataclass(frozen=True)
class OpenDictionaryIntent:
    pass


@dataclass(frozen=True)
class SaveToDictionaryIntent:
    language: str
    surface: str
    pronunciation: str


@dataclass(frozen=True)
class QuitIntent:
    pass


@dataclass(frozen=True)
class ClearCandidatesIntent:
    pass


EditorIntent = Union[
    ReplaceQueryIntent,
    PreviewIntent,
    ApplyCaptionIntent,
    BuildPronunciationIntent,
    ApplySettingsIntent,
    CloseEditorIntent,
    UpdateStatusIntent,
    AdjustmentPressedIntent,
    ClearAdjustmentFeedbackIntent,
    OpenHelpIntent,
    OpenDictionaryIntent,
    SaveToDictionaryIntent,
    QuitIntent,
    ClearCandidatesIntent,
]


@dataclass(frozen=True)
class QueryApplicationResult:
    error: str | None = None


@dataclass(frozen=True)
class CaptionApplicationResult:
    unchanged: bool = False
    initial_session_created: bool = False
    added_caption_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class BuildPronunciationResult:
    error: str | None = None


@dataclass(frozen=True)
class SettingsApplicationResult:
    error_status: Status | None = None


class TuiEditorController:
    """Own editor drafts and return typed requests for shared application changes."""

    def __init__(
        self,
        *,
        english_word_groups: Callable[[str], Sequence[tuple[str, Sequence[str]]]],
        available_styles: Callable[[], Sequence[Any]],
        input_prefix: Callable[[EditorState], str],
    ) -> None:
        self.editor: EditorState | None = None
        self.grouping_cache: dict[int, EnglishGroupingCache] = {}
        self.grouping_error: Status | None = None
        self._english_word_groups = english_word_groups
        self._available_styles = available_styles
        self._input_prefix = input_prefix

    def open_caption(
        self,
        initial: str | None,
        *,
        current_caption: str | None,
        origin: tuple[str, int | None],
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        if busy:
            return (UpdateStatusIntent("Wait for synthesis to finish before editing Caption."),)
        current = initial if initial is not None else current_caption or ""
        self.editor = EditorState(
            kind="caption",
            title="EDIT CAPTION TEXT",
            origin=origin,
            selection="draft",
            payload={"draft": current, "opening_caption": current},
        )
        return (
            UpdateStatusIntent(""),
            *self.begin_field("draft", current),
        )

    def open_build_confirmation(
        self,
        *,
        origin: tuple[str, int | None],
    ) -> tuple[EditorIntent, ...]:
        self.editor = EditorState(
            kind="build_confirmation",
            title="REBUILD PRONUNCIATION?",
            origin=origin,
            selection="rebuild",
            payload={
                "warning": "Manual pronunciation or utterance edits will be replaced."
            },
        )
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def open_settings(
        self,
        settings: Settings,
        *,
        origin: tuple[str, int | None],
        busy: bool,
        selected_field: str | None = None,
        edit: bool = False,
    ) -> tuple[EditorIntent, ...]:
        if busy:
            return (
                UpdateStatusIntent("Wait for synthesis to finish before changing settings."),
            )
        self.editor = EditorState(
            kind="settings",
            title="EDIT SETTINGS",
            origin=origin,
            selection=selected_field or "style_id",
            payload={
                "opening_settings": settings,
                "draft_settings": self._settings_draft(settings),
            },
        )
        intents: list[EditorIntent] = [UpdateStatusIntent("")]
        if edit and selected_field is not None:
            intents.extend(
                self.begin_field(
                    selected_field,
                    str(self.editor.payload["draft_settings"][selected_field]),
                )
            )
        return tuple(intents)

    @staticmethod
    def _settings_draft(settings: Settings) -> dict[str, Any]:
        return {
            "style_id": str(settings.style_id),
            "speed": str(settings.speed),
            "take_count": str(settings.take_count),
            "output_dir": str(settings.output_dir),
            "save_text": settings.save_text,
            "save_lab": settings.save_lab,
            "top_k": str(settings.top_k),
            "top_p": f"{settings.top_p:.2f}",
            "temperature": f"{settings.temperature:.2f}",
        }

    def open_add_section(
        self,
        query: AudioQuery | None,
        *,
        pure_japanese_utterance_text: str | None,
        origin: tuple[str, int | None],
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        if busy:
            return (
                UpdateStatusIntent(
                    "Wait for synthesis to finish before adding a section."
                ),
            )
        if query is None:
            return (UpdateStatusIntent(error_status("There is no active utterance.")),)
        self.editor = EditorState(
            kind="add_section",
            title="ADD SECTION",
            origin=origin,
            selection="draft",
            payload={
                "language": "ja",
                "opening_language": "ja",
                "draft": "",
                "opening_draft": "",
                "pure_japanese_utterance_text": pure_japanese_utterance_text,
            },
        )
        return (UpdateStatusIntent(""), *self.begin_field("draft", ""))

    def open_section_text(
        self,
        query: AudioQuery | None,
        *,
        pure_japanese_utterance_text: str | None,
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        parent = self.editor
        if busy or parent is None or parent.kind not in {"japanese", "english_word"}:
            return ()
        if query is None:
            return (UpdateStatusIntent(error_status("There is no active utterance.")),)

        segment_index = parent.payload["segment_index"]
        language = "ja" if parent.kind == "japanese" else "en"
        if language == "ja" and segment_index is None:
            if query.voicegerSegments is not None or pure_japanese_utterance_text is None:
                return (
                    UpdateStatusIntent(
                        error_status("The pure Japanese section text is unavailable.")
                    ),
                )
            source_text = pure_japanese_utterance_text
        else:
            if query.voicegerSegments is None or type(segment_index) is not int:
                return (UpdateStatusIntent(error_status("The selected section is unavailable.")),)
            if not 0 <= segment_index < len(query.voicegerSegments):
                return (UpdateStatusIntent(error_status("The selected section is unavailable.")),)
            segment = query.voicegerSegments[segment_index]
            if segment.language != language:
                return (UpdateStatusIntent(error_status("The selected section changed.")),)
            source_text = segment.text

        can_delete = (
            query.voicegerSegments is not None
            and len(query.voicegerSegments) > 1
        )
        payload: dict[str, Any] = {
            "language": language,
            "segment_index": segment_index,
            "opening_text": source_text,
            "draft": source_text,
            "parent_editor": deepcopy(parent),
            "can_delete": can_delete,
        }
        if language == "en":
            payload["grouping"] = parent.payload["grouping"]

        self.editor = EditorState(
            kind="section_text",
            title="EDIT SECTION TEXT",
            origin=parent.origin,
            selection="draft",
            payload=payload,
        )
        return (UpdateStatusIntent(""), *self.begin_field("draft", source_text))

    def pronunciation_rows(
        self,
        query: AudioQuery,
        segments: Sequence[tuple[str, str, int | None]],
    ) -> tuple[PronunciationRow, ...]:
        """Build selectable phrase/word rows from current canonical query data."""

        rows: list[PronunciationRow] = []
        self.grouping_error = None
        for source_index, (language, source_text, model_index) in enumerate(segments):
            first = True
            if language == "ja":
                if query.voicegerSegments is None:
                    start, count = 0, len(query.accent_phrases)
                else:
                    if model_index is None or not 0 <= model_index < len(
                        query.voicegerSegments
                    ):
                        self.grouping_error = error_status("Japanese segment references are unavailable.")
                        continue
                    segment = query.voicegerSegments[model_index]
                    start = segment.accentPhraseStart
                    count = segment.accentPhraseCount
                    if (
                        segment.language != "ja"
                        or type(start) is not int
                        or type(count) is not int
                        or count < 1
                        or start < 0
                        or start + count > len(query.accent_phrases)
                    ):
                        self.grouping_error = error_status("Japanese segment references are invalid.")
                        continue
                try:
                    canonical = japanese_pronunciation(
                        query,
                        segment_index=(
                            model_index
                            if query.voicegerSegments is not None
                            else None
                        ),
                    )
                    punctuation_suffixes = _punctuation_suffixes(canonical)
                except Exception as exc:
                    self.grouping_error = error_status(
                        f"Cannot reconstruct Japanese pronunciation: {exc}"
                    )
                    continue
                if len(punctuation_suffixes) != count:
                    self.grouping_error = error_status(
                        "Japanese pronunciation phrases do not match "
                        "their query references."
                    )
                    continue
                for local_index in range(count):
                    phrase_index = start + local_index
                    phrase = query.accent_phrases[phrase_index]
                    rows.append(
                        PronunciationRow(
                            language="ja",
                            source_text=source_text,
                            source_segment_index=source_index,
                            model_segment_index=model_index,
                            first_in_segment=first,
                            phrase_index=phrase_index,
                            phrase_index_in_segment=local_index,
                            moras=tuple(mora.text for mora in phrase.moras),
                            accent=phrase.accent,
                            punctuation_suffix=punctuation_suffixes[local_index],
                        )
                    )
                    first = False
                continue

            if language == "en" and model_index is not None:
                try:
                    grouping = self.english_grouping(query, model_index)
                except Exception as exc:
                    self.grouping_error = (
                        error_status(f"Cannot align English word pronunciation: {exc}")
                    )
                    continue
                vowel_offset = 0
                word_width = max(
                    (_display_width(group.label) for group in grouping.groups if group.editable),
                    default=0,
                )
                group_states: list[EnglishPhonemeEditorState] = []
                invalid_word_group = False
                for group in grouping.groups:
                    try:
                        group_states.append(
                            english_phonemes_to_editor_state(group.phonemes)
                        )
                    except ValueError as exc:
                        if group.editable:
                            self.grouping_error = error_status(
                                "Cannot align English word pronunciation: "
                                f"invalid word phonemes: {exc}"
                            )
                            invalid_word_group = True
                            break
                        group_state = EnglishPhonemeEditorState((), ())
                        group_states.append(group_state)
                if invalid_word_group:
                    continue

                for group_index, (group, group_state) in enumerate(
                    zip(grouping.groups, group_states)
                ):
                    if group.editable:
                        rows.append(
                            PronunciationRow(
                                language="en",
                                source_text=source_text,
                                source_segment_index=source_index,
                                model_segment_index=model_index,
                                first_in_segment=first,
                                group_index=group_index,
                                word=group.label,
                                phonemes=group.phonemes,
                                vowel_offset=vowel_offset,
                                grouping=grouping,
                            )
                        )
                        first = False
                    vowel_offset += len(group_state.vowel_stresses)
                # Keep word-column alignment data identical for every child.
                if word_width:
                    start = len(rows)
                    while start and rows[start - 1].source_segment_index == source_index:
                        start -= 1
                    for row_index in range(start, len(rows)):
                        rows[row_index] = replace(
                            rows[row_index], word_column_width=word_width
                        )
                continue

            # Retain the existing unavailable placeholder for unsupported runs.
            rows.append(
                PronunciationRow(
                    language=language,
                    source_text=source_text,
                    source_segment_index=source_index,
                    model_segment_index=model_index,
                    first_in_segment=True,
                )
            )
        return tuple(rows)

    def open_pronunciation_item(
        self,
        query: AudioQuery,
        rows: Sequence[PronunciationRow],
        index: int,
        *,
        origin: tuple[str, int | None],
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        if busy or not 0 <= index < len(rows):
            return ()
        row = rows[index]
        if row.language == "ja" and row.phrase_index is not None:
            segment_index = (
                row.model_segment_index if query.voicegerSegments is not None else None
            )
            try:
                canonical = japanese_pronunciation(
                    query,
                    segment_index=segment_index,
                )
            except Exception as exc:
                return (
                    UpdateStatusIntent(
                        error_status(f"Cannot edit Japanese pronunciation: {exc}")
                    ),
                )
            self.editor = EditorState(
                kind="japanese",
                title="EDIT PRONUNCIATION",
                origin=origin,
                selection="pronunciation",
                payload={
                    "source_text": row.source_text,
                    "canonical_pronunciation": canonical,
                    "opening_draft": canonical.replace("/", " "),
                    "segment_index": segment_index,
                },
            )
            return (
                UpdateStatusIntent(""),
                *self.begin_field("pronunciation", canonical.replace("/", " ")),
            )
        if (
            row.language == "en"
            and row.group_index is not None
            and row.grouping is not None
            and row.model_segment_index is not None
        ):
            try:
                group = row.grouping.groups[row.group_index]
                phonemes = normalize_english_phonemes(group.phonemes)
            except Exception as exc:
                return (
                    UpdateStatusIntent(
                        error_status(f"Cannot edit English word pronunciation: {exc}")
                    ),
                )
            self.editor = EditorState(
                kind="english_word",
                title="EDIT PRONUNCIATION",
                origin=origin,
                selection="phonemes",
                payload={
                    "segment_index": row.model_segment_index,
                    "group_index": row.group_index,
                    "grouping": row.grouping,
                    "label": group.label,
                    "opening_draft": " ".join(phonemes),
                },
            )
            return (
                UpdateStatusIntent(""),
                *self.begin_field("phonemes", " ".join(phonemes)),
            )
        return (
            UpdateStatusIntent(
                error_status(f"Pronunciation editing is not available for {row.language!r}.")
            ),
        )

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

    def adjust_pronunciation(
        self,
        query: AudioQuery,
        row: PronunciationRow,
        direction: int,
    ) -> tuple[EditorIntent, ...]:
        """Return a query replacement for one focused Main pronunciation row."""

        clear = (ClearAdjustmentFeedbackIntent(),)
        try:
            if row.language == "ja" and row.phrase_index is not None:
                updated = move_japanese_accent(
                    query,
                    accent_phrase_index=row.phrase_index,
                    direction=direction,
                    segment_index=(
                        row.model_segment_index
                        if query.voicegerSegments is not None
                        else None
                    ),
                )
                if updated is query:
                    return clear
                return (
                    ReplaceQueryIntent(
                        query=updated,
                        editor_kind="japanese",
                        success_status="Japanese accent updated; old takes cleared.",
                        close_editor=False,
                    ),
                )

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
                UpdateStatusIntent(error_status(f"Pronunciation was not changed: {exc}")),
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

    def begin_field(self, name: str, value: str) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        editor.selection = name
        editor.active_field = name
        editor.input_value = value
        editor.input_cursor = len(value)
        editor.input_original = value
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

    def selection_keys(self) -> list[str]:
        editor = self.editor
        if editor is None:
            return []
        return [item.key for item in menu_items(editor.kind, editor.payload)]

    def move_selection(self, delta: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        keys = self.selection_keys()
        if not keys:
            return ()
        try:
            index = keys.index(editor.selection)
        except ValueError:
            index = 0
        target = min(max(index + delta, 0), len(keys) - 1)
        if target == index:
            return ()
        editor.selection = keys[target]
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

    def move_settings_section(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "settings" or editor.active_field is not None:
            return ()
        keys = set(self.selection_keys())
        sections = tuple(
            tuple(key for key in section if key in keys)
            for section in _SETTINGS_SECTIONS
        )
        sections = tuple(section for section in sections if section)
        if not sections:
            return ()
        current = next(
            (
                index
                for index, section in enumerate(sections)
                if editor.selection in section
            ),
            0,
        )
        target = (current + (1 if direction > 0 else -1)) % len(sections)
        editor.selection = sections[target][0]
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

    def handle_key(
        self,
        key: Any,
        *,
        settings: Settings,
        query: AudioQuery | None,
        current_caption: str | None,
        screen_width: int = 80,
        preview_busy: bool = False,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if preview_busy and editor.kind in {"japanese", "english_word", "section_text"}:
            return (
                UpdateStatusIntent(
                    "Wait for Preview to finish before editing section text."
                    if editor.kind == "section_text"
                    else "Wait for Preview to finish before editing pronunciation."
                ),
            )
        if editor.active_field is not None:
            if key in _ENTER_KEYS:
                return self._finish_field()
            if key == _ESCAPE:
                if editor.kind in {
                    "caption", "japanese", "settings", "english_word",
                    "section_text", "add_section",
                }:
                    return self.cancel()
                editor.input_value = editor.input_original
                editor.input_cursor = len(editor.input_original)
                editor.active_field = None
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent(""),)
            if editor.kind == "japanese" and isinstance(key, str) and "/" in key:
                editor.error = (
                    error_status("Use spaces for phrase boundaries; '/' is not used in this editor.")
                )
                return ()
            input_changed = False
            if key == curses.KEY_LEFT:
                editor.input_cursor = max(0, editor.input_cursor - 1)
            elif key == curses.KEY_RIGHT:
                editor.input_cursor = min(len(editor.input_value), editor.input_cursor + 1)
            elif key == curses.KEY_HOME or key == "\x01":
                editor.input_cursor = 0
            elif key == curses.KEY_END or key == "\x05":
                editor.input_cursor = len(editor.input_value)
            elif key in (curses.KEY_UP, curses.KEY_DOWN):
                prefix = self._input_prefix(editor)
                input_width = max(1, screen_width - 1 - _display_width(prefix))
                editor.input_cursor = _move_wrapped_cursor(
                    editor.input_value,
                    editor.input_cursor,
                    -1 if key == curses.KEY_UP else 1,
                    input_width,
                )
            elif key in (curses.KEY_BACKSPACE, "\x7f", "\x08"):
                if editor.input_cursor:
                    editor.input_value = (
                        editor.input_value[: editor.input_cursor - 1]
                        + editor.input_value[editor.input_cursor :]
                    )
                    editor.input_cursor -= 1
                    input_changed = True
            elif key == curses.KEY_DC:
                if editor.input_cursor < len(editor.input_value):
                    editor.input_value = (
                        editor.input_value[: editor.input_cursor]
                        + editor.input_value[editor.input_cursor + 1 :]
                    )
                    input_changed = True
            elif isinstance(key, str) and key and all(
                char.isprintable() or char == "　" for char in key
            ):
                editor.input_value = (
                    editor.input_value[: editor.input_cursor]
                    + key
                    + editor.input_value[editor.input_cursor :]
                )
                editor.input_cursor += len(key)
                input_changed = True
            if input_changed and editor.kind in {
                "japanese", "english_word", "section_text", "add_section"
            }:
                editor.error = EMPTY_STATUS
            return ()

        if key in ("q", "Q", "\x03"):
            return (QuitIntent(),)
        if key == "?":
            return (OpenHelpIntent(),)
        if editor.kind == "settings":
            if key == "\t":
                return self.move_settings_section(1)
            backtab = getattr(curses, "KEY_BTAB", None)
            if backtab is not None and key == backtab:
                return self.move_settings_section(-1)
        shortcut = resolve_shortcut(editor.kind, key, editor.payload)
        if shortcut is not None:
            editor.selection = shortcut.key
            editor.error = EMPTY_STATUS
            if shortcut.shortcut_mode == "focus":
                return (ClearAdjustmentFeedbackIntent(),)
            return self._activate_selection(settings, query, current_caption)

        if editor.kind == "settings" and key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            return self.adjust_settings(-1 if key == curses.KEY_LEFT else 1)
        if (
            editor.kind == "add_section"
            and editor.selection == "language"
            and key in (curses.KEY_LEFT, curses.KEY_RIGHT)
        ):
            language = editor.payload["language"]
            if (key == curses.KEY_RIGHT and language == "ja") or (
                key == curses.KEY_LEFT and language == "en"
            ):
                editor.payload["language"] = "en" if language == "ja" else "ja"
                editor.error = EMPTY_STATUS
                return (ClearAdjustmentFeedbackIntent(), UpdateStatusIntent(""))
            return ()
        if key == _ESCAPE:
            return self.cancel()
        if key == curses.KEY_UP:
            return self.move_selection(-1)
        if key == curses.KEY_DOWN:
            return self.move_selection(1)
        if key in _ENTER_KEYS:
            return self._activate_selection(settings, query, current_caption)
        return ()

    def _activate_selection(
        self,
        settings: Settings,
        query: AudioQuery | None,
        current_caption: str | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        selected = editor.selection
        if editor.kind == "caption":
            if selected == "draft":
                return self.begin_field("draft", editor.payload["draft"])
            if selected == "apply":
                return self.apply(settings, query, current_caption)
            if selected == "clear":
                self._set_caption_draft(editor, "")
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("Caption draft cleared."),)
            if selected == "reset":
                self._set_caption_draft(
                    editor, editor.payload["opening_caption"]
                )
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("Caption draft reset."),)
            if selected == "back":
                return self.cancel()
        elif editor.kind == "build_confirmation":
            if selected == "rebuild":
                return (BuildPronunciationIntent(),)
            if selected == "cancel":
                return self._close_editor("Pronunciation rebuild cancelled.")
        elif editor.kind == "japanese":
            if selected == "pronunciation":
                return self.begin_field("pronunciation", editor.input_value)
            if selected == "preview":
                return self.preview(query)
            if selected == "apply":
                return self.apply(settings, query, current_caption)
            if selected == "save_dictionary":
                return (
                    SaveToDictionaryIntent(
                        language="ja",
                        surface=editor.payload["source_text"],
                        pronunciation=editor.input_value,
                    ),
                )
            if selected == "dictionary":
                return (OpenDictionaryIntent(),)
            if selected == "edit_text":
                return self.open_section_text(
                    query,
                    pure_japanese_utterance_text=(
                        editor.payload["source_text"]
                        if editor.payload["segment_index"] is None
                        else None
                    ),
                    busy=False,
                )
            if selected == "clear":
                self._set_pronunciation_draft(editor, "")
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("Japanese pronunciation draft cleared."),)
            if selected == "reset":
                self._set_pronunciation_draft(
                    editor, editor.payload["opening_draft"]
                )
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("Japanese pronunciation draft reset."),)
            if selected == "back":
                return self.cancel()
        elif editor.kind == "settings":
            if selected in {"style_id", "speed", "save_text", "save_lab", "apply"}:
                return self.apply(settings, query, current_caption)
            if selected in {
                "take_count", "output_dir", "top_k", "top_p", "temperature"
            }:
                value = editor.payload["draft_settings"][selected]
                return self.begin_field(selected, str(value))
            if selected == "reset_sampling":
                draft = editor.payload["draft_settings"]
                draft["top_k"] = str(VOICEGER_DEFAULT_TOP_K)
                draft["top_p"] = f"{VOICEGER_DEFAULT_TOP_P:.2f}"
                draft["temperature"] = f"{VOICEGER_DEFAULT_TEMPERATURE:.2f}"
                editor.error = EMPTY_STATUS
                return (
                    ClearAdjustmentFeedbackIntent(),
                    UpdateStatusIntent("Sampling reset to Voiceger defaults."),
                )
            if selected == "reset":
                editor.payload["draft_settings"] = self._settings_draft(
                    editor.payload["opening_settings"]
                )
                editor.error = EMPTY_STATUS
                return (
                    ClearAdjustmentFeedbackIntent(),
                    UpdateStatusIntent("Settings draft reset."),
                )
            if selected == "back":
                return self.cancel()
        elif editor.kind == "english_word":
            if selected == "phonemes":
                return self.begin_field("phonemes", editor.input_value)
            if selected == "preview":
                return self.preview(query)
            if selected == "apply":
                return self.apply(settings, query, current_caption)
            if selected == "save_dictionary":
                return (
                    SaveToDictionaryIntent(
                        language="en",
                        surface=editor.payload["label"],
                        pronunciation=editor.input_value,
                    ),
                )
            if selected == "dictionary":
                return (OpenDictionaryIntent(),)
            if selected == "edit_text":
                return self.open_section_text(
                    query,
                    pure_japanese_utterance_text=None,
                    busy=False,
                )
            if selected == "clear":
                self._set_pronunciation_draft(editor, "")
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("English phoneme draft cleared."),)
            if selected == "reset":
                self._set_pronunciation_draft(
                    editor, editor.payload["opening_draft"]
                )
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("English phoneme draft reset."),)
            if selected == "back":
                return self.cancel()
        elif editor.kind == "section_text":
            if selected == "draft":
                return self.begin_field("draft", editor.input_value)
            if selected == "preview":
                return self.preview_section_text(query)
            if selected == "apply":
                return self.apply_section_text(query)
            if selected == "reset":
                self._set_text_draft(editor, editor.payload["opening_text"])
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("Section text draft reset."),)
            if selected == "delete_section":
                return self.open_delete_confirmation()
            if selected == "back":
                return self.cancel()
        elif editor.kind == "add_section":
            if selected == "draft":
                return self.begin_field("draft", editor.input_value)
            if selected == "add":
                return self.add_section(query)
            if selected == "clear":
                self._set_text_draft(editor, "")
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("New section draft cleared."),)
            if selected == "reset":
                editor.payload["language"] = editor.payload["opening_language"]
                self._set_text_draft(editor, editor.payload["opening_draft"])
                editor.error = EMPTY_STATUS
                return (UpdateStatusIntent("New section draft reset."),)
            if selected == "back":
                return self.cancel()
        elif editor.kind == "delete_confirmation":
            if selected == "delete":
                return self.delete_section(query)
            if selected == "cancel":
                return self._restore_parent_editor("Section deletion cancelled.")
        elif editor.kind == "clear_candidates_confirmation":
            if selected == "clear":
                origin = editor.origin
                self.editor = None
                return (
                    ClearCandidatesIntent(),
                    ClearAdjustmentFeedbackIntent(),
                    CloseEditorIntent(origin, "Candidates cleared."),
                )
            if selected == "cancel":
                return self._close_editor("Candidate clearing cancelled.")
        return ()

    @staticmethod
    def _set_caption_draft(editor: EditorState, caption: str) -> None:
        editor.payload["draft"] = caption
        editor.input_value = caption
        editor.input_original = caption
        editor.input_cursor = len(caption)

    @staticmethod
    def _set_pronunciation_draft(editor: EditorState, value: str) -> None:
        field = "pronunciation" if editor.kind == "japanese" else "phonemes"
        editor.input_value = value
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.active_field = None
        editor.payload[field] = value

    @staticmethod
    def _set_text_draft(editor: EditorState, value: str) -> None:
        editor.payload["draft"] = value
        editor.input_value = value
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.active_field = None

    @staticmethod
    def _word_group_values(
        grouping: EnglishGroupingCache,
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple((group.label, group.phonemes) for group in grouping.groups)

    @staticmethod
    def _grouping_cache(
        source_text: str,
        groups: Sequence[tuple[str, Sequence[str]]],
    ) -> EnglishGroupingCache:
        return EnglishGroupingCache(
            source_text,
            tuple(
                EnglishWordGroup(
                    label=label,
                    phonemes=tuple(phonemes),
                    editable=any(character.isalpha() for character in label),
                )
                for label, phonemes in groups
            ),
        )

    @staticmethod
    def _validated_text(editor: EditorState) -> str:
        text = editor.payload["draft"]
        language = "Japanese" if editor.payload["language"] == "ja" else "English"
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{language} section text must not be empty")
        if "\n" in text or "\r" in text:
            raise ValueError(f"{language} section text must not contain newlines")
        return text

    def preview_section_text(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "section_text":
            return ()
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            text = self._validated_text(editor)
            if editor.payload["language"] == "ja":
                preview_query = japanese_section_text_preview_query(
                    query,
                    text,
                    segment_index=editor.payload["segment_index"],
                )
            else:
                grouping: EnglishGroupingCache = editor.payload["grouping"]
                preview_query = english_section_text_preview_query(
                    query,
                    segment_index=editor.payload["segment_index"],
                    text=text,
                    old_groups=self._word_group_values(grouping),
                    new_groups=self._english_word_groups(text),
                )
        except Exception as exc:
            editor.error = error_status(f"Preview failed: {exc}")
            return ()
        editor.error = EMPTY_STATUS
        return (PreviewIntent(preview_query),)

    def apply_section_text(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "section_text":
            return ()
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            text = self._validated_text(editor)
            if text == editor.payload["opening_text"]:
                return self._close_editor("Section text unchanged.")
            segment_index = editor.payload["segment_index"]
            accepted_grouping = None
            if editor.payload["language"] == "ja":
                updated = replace_japanese_section_text(
                    query,
                    text,
                    segment_index=segment_index,
                )
                pure_text = text if segment_index is None else None
            else:
                grouping: EnglishGroupingCache = editor.payload["grouping"]
                merged = merge_english_section_text_groups(
                    query,
                    segment_index=segment_index,
                    old_groups=self._word_group_values(grouping),
                    new_groups=self._english_word_groups(text),
                )
                updated = replace_english_section_text(
                    query,
                    segment_index=segment_index,
                    text=text,
                    phoneme_groups=merged,
                )
                accepted_grouping = self._grouping_cache(text, merged)
                pure_text = None
        except Exception as exc:
            editor.error = error_status(f"Section text was not changed: {exc}")
            return ()
        return (
            ReplaceQueryIntent(
                query=updated,
                editor_kind="section_text",
                success_status="Section text updated; old takes cleared.",
                grouping_index=(
                    segment_index if accepted_grouping is not None else None
                ),
                accepted_grouping=accepted_grouping,
                pure_japanese_utterance_text=pure_text,
            ),
        )

    def open_delete_confirmation(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if (
            editor is None
            or editor.kind != "section_text"
            or not editor.payload["can_delete"]
        ):
            return ()
        self.editor = EditorState(
            kind="delete_confirmation",
            title="DELETE SECTION?",
            origin=editor.origin,
            selection="delete",
            payload={
                "warning": "This section will be removed from the synthesized utterance.",
                "parent_editor": deepcopy(editor),
            },
        )
        return (ClearAdjustmentFeedbackIntent(), UpdateStatusIntent(""))

    def open_clear_candidates_confirmation(
        self,
        *,
        origin: tuple[str, int | None],
    ) -> tuple[EditorIntent, ...]:
        self.editor = EditorState(
            kind="clear_candidates_confirmation",
            title="CLEAR CANDIDATES?",
            origin=origin,
            selection="clear",
            payload={
                "warning": (
                    "All generated candidate WAV files will be discarded."
                ),
            },
        )
        return (ClearAdjustmentFeedbackIntent(), UpdateStatusIntent(""))

    def delete_section(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        confirmation = self.editor
        if confirmation is None or confirmation.kind != "delete_confirmation":
            return ()
        section_editor: EditorState = confirmation.payload["parent_editor"]
        self.editor = section_editor
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            segment_index = section_editor.payload["segment_index"]
            if type(segment_index) is not int:
                raise ValueError("pure Japanese utterances cannot delete their only section")
            updated, pure_text = delete_utterance_section(
                query,
                segment_index=segment_index,
            )
        except Exception as exc:
            section_editor.error = error_status(f"Section was not deleted: {exc}")
            return ()
        return (
            ReplaceQueryIntent(
                query=updated,
                editor_kind="delete_section",
                success_status="Section deleted; old takes cleared.",
                deleted_segment_index=segment_index,
                pure_japanese_utterance_text=pure_text,
            ),
        )

    def add_section(
        self,
        query: AudioQuery | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "add_section":
            return ()
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            text = self._validated_text(editor)
            language = editor.payload["language"]
            pure_text = editor.payload["pure_japanese_utterance_text"]
            if language == "ja":
                updated = append_japanese_section(
                    query,
                    text,
                    pure_japanese_utterance_text=pure_text,
                )
                accepted_grouping = None
                grouping_index = None
            else:
                generated = self._english_word_groups(text)
                updated = append_english_section(
                    query,
                    text,
                    phoneme_groups=generated,
                    pure_japanese_utterance_text=pure_text,
                )
                assert updated.voicegerSegments is not None
                grouping_index = len(updated.voicegerSegments) - 1
                accepted_grouping = self._grouping_cache(text, generated)
        except Exception as exc:
            editor.error = error_status(f"Section was not added: {exc}")
            return ()
        language_name = "Japanese" if language == "ja" else "English"
        return (
            ReplaceQueryIntent(
                query=updated,
                editor_kind="add_section",
                success_status=f"{language_name} section added; old takes cleared.",
                grouping_index=grouping_index,
                accepted_grouping=accepted_grouping,
            ),
        )

    def preview(self, query: AudioQuery | None) -> tuple[EditorIntent, ...]:
        """Validate a pronunciation draft and emit a transient query intent."""

        editor = self.editor
        if editor is None or editor.kind not in {"japanese", "english_word"}:
            return ()
        try:
            if query is None:
                raise ValueError("There is no active utterance")
            if editor.kind == "japanese":
                draft = editor.input_value
                if "/" in draft:
                    raise ValueError(
                        "Use spaces for phrase boundaries; '/' is not used in this editor."
                    )
                canonical = draft.replace("　", "/").replace(" ", "/")
                preview_query = japanese_preview_query(
                    query,
                    canonical,
                    segment_index=editor.payload["segment_index"],
                )
            else:
                grouping: EnglishGroupingCache = editor.payload["grouping"]
                draft_phonemes = normalize_english_phonemes(
                    editor.input_value.split()
                )
                preview_query = english_word_preview_query(
                    query,
                    segment_index=editor.payload["segment_index"],
                    group_index=editor.payload["group_index"],
                    phoneme_groups=tuple(
                        group.phonemes for group in grouping.groups
                    ),
                    draft_phonemes=draft_phonemes,
                )
        except Exception as exc:
            editor.error = error_status(f"Preview failed: {exc}")
            return ()
        editor.error = EMPTY_STATUS
        return (PreviewIntent(preview_query),)

    def _finish_field(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.active_field is None:
            return ()
        name = editor.active_field
        value = editor.input_value
        if editor.kind == "settings" and name == "take_count":
            try:
                take_count = int(value)
            except (TypeError, ValueError):
                editor.error = (
                    error_status("Take count must be an integer from 1 through 100.")
                )
                return ()
            if not 1 <= take_count <= 100:
                editor.error = (
                    error_status("Take count must be an integer from 1 through 100.")
                )
                return ()
            value = str(take_count)
            editor.input_value = value
        elif editor.kind == "settings" and name == "top_k":
            try:
                top_k = int(value)
            except (TypeError, ValueError):
                editor.error = error_status("Top K must be an integer from 1 through 100.")
                return ()
            if not 1 <= top_k <= 100:
                editor.error = error_status("Top K must be an integer from 1 through 100.")
                return ()
            value = str(top_k)
            editor.input_value = value
        elif editor.kind == "settings" and name in {"top_p", "temperature"}:
            label = "Top P" if name == "top_p" else "Temperature"
            try:
                numeric = Decimal(value)
            except (InvalidOperation, TypeError, ValueError):
                editor.error = (
                    error_status(f"{label} must be a finite number from 0.00 through 1.00.")
                )
                return ()
            if not numeric.is_finite() or not Decimal("0") <= numeric <= Decimal("1"):
                editor.error = (
                    error_status(f"{label} must be a finite number from 0.00 through 1.00.")
                )
                return ()
            value = f"{numeric:.2f}"
            editor.input_value = value
        elif editor.kind == "japanese" and name == "pronunciation":
            value = "".join(
                canonicalize_punctuation(character) or character
                for character in value
            )
            editor.input_value = value
        if editor.kind == "settings":
            editor.payload["draft_settings"][name] = value
        else:
            editor.payload[name] = value
        editor.active_field = None
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = EMPTY_STATUS
        if editor.kind == "settings":
            status = ""
        else:
            status = ""
        return (UpdateStatusIntent(status),)

    def apply(
        self,
        settings: Settings,
        query: AudioQuery | None,
        current_caption: str | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.kind == "caption":
            source = editor.payload["draft"]
            if current_caption is not None and source == current_caption:
                return self._close_editor("Caption unchanged.")
            return (ApplyCaptionIntent(source),)
        if editor.kind == "japanese":
            try:
                if query is None:
                    raise ValueError("There is no active utterance")
                draft = editor.input_value
                if "/" in draft:
                    raise ValueError(
                        "Use spaces for phrase boundaries; '/' is not used in this editor."
                    )
                canonical = draft.replace("　", "/").replace(" ", "/")
                if canonical == editor.payload["canonical_pronunciation"]:
                    return self._close_editor("Japanese pronunciation unchanged.")
                updated = replace_japanese_pronunciation(
                    query,
                    canonical,
                    segment_index=editor.payload["segment_index"],
                )
            except Exception as exc:
                editor.error = error_status(f"Pronunciation was not changed: {exc}")
                return ()
            return (
                ReplaceQueryIntent(
                    query=updated,
                    editor_kind="japanese",
                    success_status="Japanese pronunciation updated; old takes cleared.",
                ),
            )
        if editor.kind == "english_word":
            index = editor.payload["segment_index"]
            group_index = editor.payload["group_index"]
            grouping: EnglishGroupingCache = editor.payload["grouping"]
            try:
                if query is None:
                    raise ValueError("There is no active utterance")
                groups = list(grouping.groups)
                edited_phones = tuple(
                    normalize_english_phonemes(editor.input_value.split())
                )
                current_phones = tuple(
                    normalize_english_phonemes(groups[group_index].phonemes)
                )
                if edited_phones == current_phones:
                    return self._close_editor("English phonemes unchanged.")
                groups[group_index] = replace(
                    groups[group_index],
                    phonemes=edited_phones,
                )
                updated = replace_english_phoneme_groups(
                    query,
                    segment_index=index,
                    phoneme_groups=tuple(group.phonemes for group in groups),
                )
            except Exception as exc:
                editor.error = error_status(f"English phonemes were not changed: {exc}")
                return ()
            accepted_grouping = EnglishGroupingCache(
                grouping.source_text, tuple(groups)
            )
            return (
                ReplaceQueryIntent(
                    query=updated,
                    editor_kind="english_word",
                    success_status="English word pronunciation updated; old takes cleared.",
                    grouping_index=index,
                    accepted_grouping=accepted_grouping,
                ),
            )
        if editor.kind == "settings":
            return self._apply_settings(settings)
        return ()

    def _apply_settings(self, settings: Settings) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        draft = editor.payload["draft_settings"]
        try:
            updated = Settings(
                style_id=int(draft["style_id"]),
                speed=float(draft["speed"]),
                take_count=int(draft["take_count"]),
                output_dir=Path(draft["output_dir"]),
                save_text=draft["save_text"],
                save_lab=draft["save_lab"],
                top_k=int(draft["top_k"]),
                top_p=float(draft["top_p"]),
                temperature=float(draft["temperature"]),
            )
        except (TypeError, ValueError, SettingsError) as exc:
            editor.error = error_status(f"Settings were not changed: {exc}")
            return ()
        return (ApplySettingsIntent(updated),)

    def complete_query_application(
        self,
        intent: ReplaceQueryIntent,
        result: QueryApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if result.error is not None:
            if editor is None:
                return (UpdateStatusIntent(error_status(f"Query was not changed: {result.error}")),)
            error_prefix = {
                "japanese": "Pronunciation was not changed",
                "english_word": "English pronunciation was not changed",
                "section_text": "Section text was not changed",
                "add_section": "Section was not added",
                "delete_section": "Section was not deleted",
            }.get(intent.editor_kind, "Query was not changed")
            editor.error = error_status(f"{error_prefix}: {result.error}")
            return ()
        if intent.deleted_segment_index is not None:
            self.remap_groupings_after_deletion(
                intent.deleted_segment_index,
                intent.query,
            )
        else:
            self.reconcile_groupings(intent.query)
        if intent.grouping_index is not None and intent.accepted_grouping is not None:
            self.grouping_cache[intent.grouping_index] = intent.accepted_grouping
        if not intent.close_editor:
            return (UpdateStatusIntent(intent.success_status),)
        if editor is None:
            return ()
        return self._close_editor(intent.success_status)

    def complete_caption_application(
        self,
        result: CaptionApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if result.error is not None:
            editor.error = error_status(f"Caption was not changed: {result.error}")
            return ()
        if result.unchanged:
            return self._close_editor("Caption unchanged.")
        if result.added_caption_count:
            count = result.added_caption_count
            status = (
                "Caption added."
                if count == 1
                else f"{count} Captions added."
            )
        else:
            status = (
                "Caption set."
                if result.initial_session_created
                else "Caption updated."
            )
        return self._close_editor(status)

    def complete_build_confirmation(
        self,
        result: BuildPronunciationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if result.error is not None:
            if editor is None:
                return (
                    UpdateStatusIntent(
                        error_status(f"Pronunciation was not rebuilt: {result.error}")
                    ),
                )
            editor.error = error_status(f"Pronunciation was not rebuilt: {result.error}")
            return ()
        self.editor = None
        return (ClearAdjustmentFeedbackIntent(),)

    def complete_settings_application(
        self,
        result: SettingsApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if result.error_status is not None:
            editor.error = result.error_status
            return ()
        return self._close_editor("Settings saved.")

    def cancel(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.kind in {"section_text", "delete_confirmation"}:
            status = (
                "Section text draft discarded."
                if editor.kind == "section_text"
                else "Section deletion cancelled."
            )
            return self._restore_parent_editor(status)
        status = {
            "caption": "Caption draft discarded.",
            "build_confirmation": "Pronunciation rebuild cancelled.",
            "japanese": "Japanese pronunciation draft discarded.",
            "settings": "Settings draft discarded.",
            "english_word": "English word draft discarded.",
            "add_section": "New section draft discarded.",
            "clear_candidates_confirmation": "Candidate clearing cancelled.",
        }.get(editor.kind, "Editor draft discarded.")
        return self._close_editor(status)

    def _restore_parent_editor(self, status: str) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        parent = editor.payload.get("parent_editor")
        if not isinstance(parent, EditorState):
            return self._close_editor(status)
        self.editor = parent
        return (ClearAdjustmentFeedbackIntent(), UpdateStatusIntent(status))

    def _close_editor(self, status: str) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        origin = editor.origin
        self.editor = None
        return (ClearAdjustmentFeedbackIntent(), CloseEditorIntent(origin, status))

    def adjust_settings(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "settings" or editor.active_field is not None:
            return ()
        draft = editor.payload["draft_settings"]
        selected = editor.selection
        if selected not in {
            "style_id", "speed", "take_count", "save_text", "save_lab",
            "top_k", "top_p", "temperature",
        }:
            return ()
        clear_feedback = (ClearAdjustmentFeedbackIntent(),)
        feedback = AdjustmentPressedIntent("settings", selected, direction)
        if selected == "style_id":
            styles = self._available_styles()
            if not styles:
                editor.error = error_status("No available styles can be selected.")
                return clear_feedback
            try:
                current_id = int(draft["style_id"])
            except (TypeError, ValueError):
                editor.error = error_status("Style ID must be a positive integer.")
                return clear_feedback
            index = next(
                (i for i, style in enumerate(styles) if style.id == current_id),
                None,
            )
            if index is None:
                editor.error = error_status(f"Style ID {current_id} is not available.")
                return clear_feedback
            target = index + direction
            if not 0 <= target < len(styles):
                return clear_feedback
            updated_id = styles[target].id
            if updated_id == current_id:
                return clear_feedback
            draft["style_id"] = str(updated_id)
        elif selected == "speed":
            try:
                current = Decimal(str(draft["speed"]))
                if not current.is_finite() or current <= 0:
                    raise InvalidOperation
                current = current.quantize(Decimal("0.01"))
                updated = current + Decimal("0.01") * direction
                updated = max(Decimal("0.01"), updated)
            except (InvalidOperation, ValueError):
                editor.error = error_status("Speed must be a positive finite number.")
                return clear_feedback
            if updated == current:
                editor.error = EMPTY_STATUS
                return clear_feedback
            draft["speed"] = f"{updated:.2f}"
        elif selected == "take_count":
            try:
                current = int(draft["take_count"])
            except (TypeError, ValueError):
                editor.error = error_status("Take count must be an integer from 1 through 100.")
                return clear_feedback
            updated = min(100, max(1, current + direction))
            if updated == current:
                editor.error = EMPTY_STATUS
                return clear_feedback
            draft["take_count"] = str(updated)
        elif selected == "top_k":
            try:
                current = int(draft["top_k"])
            except (TypeError, ValueError):
                editor.error = error_status("Top K must be an integer from 1 through 100.")
                return clear_feedback
            if not 1 <= current <= 100:
                editor.error = error_status("Top K must be an integer from 1 through 100.")
                return clear_feedback
            updated = min(100, max(1, current + direction))
            if updated == current:
                editor.error = EMPTY_STATUS
                return clear_feedback
            draft["top_k"] = str(updated)
        elif selected in {"top_p", "temperature"}:
            label = "Top P" if selected == "top_p" else "Temperature"
            try:
                current = Decimal(str(draft[selected]))
            except (InvalidOperation, TypeError, ValueError):
                editor.error = (
                    error_status(f"{label} must be a finite number from 0.00 through 1.00.")
                )
                return clear_feedback
            if (
                not current.is_finite()
                or not Decimal("0") <= current <= Decimal("1")
            ):
                editor.error = (
                    error_status(f"{label} must be a finite number from 0.00 through 1.00.")
                )
                return clear_feedback
            updated = current + Decimal("0.05") * direction
            updated = min(Decimal("1.00"), max(Decimal("0.00"), updated))
            if updated == current:
                editor.error = EMPTY_STATUS
                return clear_feedback
            draft[selected] = f"{updated:.2f}"
        elif selected in {"save_text", "save_lab"}:
            draft[selected] = not bool(draft[selected])
        editor.error = EMPTY_STATUS
        return (feedback,)
