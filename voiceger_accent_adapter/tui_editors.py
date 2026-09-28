"""Editor state, interaction policy, and application intent boundaries."""

from __future__ import annotations

import curses
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Sequence, Union

from .english_stress import (
    EnglishPhonemeEditorState,
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
    replace_editor_base_phonemes,
)
from .query_editing import (
    japanese_pronunciation,
    replace_english_phoneme_groups,
    replace_japanese_pronunciation,
)
from .settings import Settings, SettingsError
from .tui_display import _display_width, _move_wrapped_cursor
from .voicevox_api_models import AudioQuery


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"


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
    error: str = ""
    scroll: int = 0


@dataclass(frozen=True)
class ReplaceQueryIntent:
    query: AudioQuery
    editor_kind: str
    success_status: str
    grouping_index: int | None = None
    accepted_grouping: EnglishGroupingCache | None = None


@dataclass(frozen=True)
class ReplaceSourceTextIntent:
    source_text: str


@dataclass(frozen=True)
class SettingsChanges:
    style_id: int | None = None
    speed: float | None = None
    take_count: int | None = None
    output_dir: Path | None = None
    save_text: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in (
                ("style_id", self.style_id),
                ("speed", self.speed),
                ("take_count", self.take_count),
                ("output_dir", self.output_dir),
                ("save_text", self.save_text),
            )
            if value is not None
        }


@dataclass(frozen=True)
class ApplySettingsIntent:
    changes: SettingsChanges


@dataclass(frozen=True)
class CloseEditorIntent:
    origin: tuple[str, int | None]
    status: str


@dataclass(frozen=True)
class UpdateStatusIntent:
    status: str


@dataclass(frozen=True)
class AdjustmentPressedIntent:
    area: str
    control: str
    direction: int


@dataclass(frozen=True)
class ClearAdjustmentFeedbackIntent:
    pass


EditorIntent = Union[
    ReplaceQueryIntent,
    ReplaceSourceTextIntent,
    ApplySettingsIntent,
    CloseEditorIntent,
    UpdateStatusIntent,
    AdjustmentPressedIntent,
    ClearAdjustmentFeedbackIntent,
]


@dataclass(frozen=True)
class QueryApplicationResult:
    error: str | None = None


@dataclass(frozen=True)
class SourceTextApplicationResult:
    unchanged: bool = False
    needs_rebuild: bool = False
    error: str | None = None


@dataclass(frozen=True)
class SettingsApplicationResult:
    error_status: str | None = None


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
        self._english_word_groups = english_word_groups
        self._available_styles = available_styles
        self._input_prefix = input_prefix

    @staticmethod
    def first_editable_word_key(
        groups: Sequence[EnglishWordGroup],
    ) -> str | tuple[str, int | None]:
        for index, group in enumerate(groups):
            if group.editable:
                return ("word", index)
        return "apply"

    def open_text(
        self,
        initial: str | None,
        *,
        current_source: str | None,
        origin: tuple[str, int | None],
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        if busy:
            return (UpdateStatusIntent("Wait for synthesis to finish before editing text."),)
        current = initial if initial is not None else current_source or ""
        self.editor = EditorState(
            kind="text",
            title="EDIT TEXT",
            origin=origin,
            selection="draft",
            payload={"draft": current},
        )
        return (
            UpdateStatusIntent(""),
            *self.begin_field("draft", current),
        )

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
        draft = {
            "style_id": str(settings.style_id),
            "speed": str(settings.speed),
            "take_count": str(settings.take_count),
            "output_dir": str(settings.output_dir),
            "save_text": settings.save_text,
        }
        self.editor = EditorState(
            kind="settings",
            title="EDIT SETTINGS",
            origin=origin,
            selection=selected_field or "style_id",
            payload={"draft_settings": draft},
        )
        intents: list[EditorIntent] = [UpdateStatusIntent("")]
        if edit and selected_field is not None:
            intents.extend(self.begin_field(selected_field, str(draft[selected_field])))
        return tuple(intents)

    def open_segment(
        self,
        query: AudioQuery,
        segments: Sequence[tuple[str, str, int | None]],
        index: int,
        *,
        origin: tuple[str, int | None],
        busy: bool,
    ) -> tuple[EditorIntent, ...]:
        if busy or not 0 <= index < len(segments):
            return ()
        language, segment_text, model_index = segments[index]
        if language == "ja":
            try:
                segment_model_index = (
                    model_index if query.voicegerSegments is not None else None
                )
                current = japanese_pronunciation(
                    query,
                    segment_index=segment_model_index,
                )
            except Exception as exc:
                return (
                    UpdateStatusIntent(
                        f"Error: Cannot render Japanese pronunciation: {exc}"
                    ),
                )
            self.editor = EditorState(
                kind="japanese",
                title="EDIT JAPANESE PRONUNCIATION",
                origin=origin,
                selection="draft",
                payload={
                    "source_text": segment_text,
                    "draft": current,
                    "segment_index": segment_model_index,
                },
            )
            return (
                UpdateStatusIntent(""),
                *self.begin_field("draft", current),
            )
        if language == "en" and model_index is not None:
            try:
                grouping = self.english_grouping(query, model_index)
            except Exception as exc:
                return (
                    UpdateStatusIntent(
                        f"Error: Cannot align English word pronunciation: {exc}"
                    ),
                )
            self.editor = EditorState(
                kind="english_segment",
                title="EDIT ENGLISH SEGMENT",
                origin=origin,
                selection=self.first_editable_word_key(grouping.groups),
                payload={
                    "segment_index": model_index,
                    "source_text": segment_text,
                    "groups": grouping.groups,
                },
            )
            return (UpdateStatusIntent(""),)
        return (
            UpdateStatusIntent(
                f"Error: Pronunciation editing is not available for {language!r}."
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

    def clear_groupings(self) -> None:
        self.grouping_cache.clear()

    def begin_field(self, name: str, value: str) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        editor.selection = name
        editor.active_field = name
        editor.input_value = value
        editor.input_cursor = len(value)
        editor.input_original = value
        editor.error = ""
        return (ClearAdjustmentFeedbackIntent(),)

    def selection_keys(self) -> list[str | tuple[str, int | None]]:
        editor = self.editor
        if editor is None:
            return []
        if editor.kind in {"text", "japanese"}:
            return ["draft"]
        if editor.kind == "settings":
            return [
                "style_id", "speed", "take_count", "output_dir", "save_text", "apply",
            ]
        if editor.kind == "english_segment":
            keys = [
                ("word", index)
                for index, group in enumerate(editor.payload["groups"])
                if group.editable
            ]
            return keys + ["apply", "cancel"]
        if editor.kind == "english_word":
            state: EnglishPhonemeEditorState = editor.payload["draft_state"]
            keys: list[str | tuple[str, int | None]] = ["phonemes"]
            keys.extend(
                ("primary", index)
                for index, _position in enumerate(state.primary_stress_vowel_positions)
            )
            return keys + ["done", "cancel"]
        return []

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
        editor.error = ""
        return (ClearAdjustmentFeedbackIntent(),)

    def handle_key(
        self,
        key: Any,
        *,
        settings: Settings,
        query: AudioQuery | None,
        current_source: str | None,
        screen_width: int = 80,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.active_field is not None:
            if key in _ENTER_KEYS:
                if editor.kind in {"text", "japanese"}:
                    editor.payload["draft"] = editor.input_value
                    return self.apply(settings, query, current_source)
                return self._finish_field()
            if key == _ESCAPE:
                if editor.kind in {"text", "japanese", "settings"}:
                    return self.cancel()
                if editor.kind == "english_word":
                    return self.cancel_word()
                editor.input_value = editor.input_original
                editor.input_cursor = len(editor.input_original)
                editor.active_field = None
                editor.error = ""
                return (UpdateStatusIntent("Field edit canceled; the editor draft is unchanged."),)
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
            elif key == curses.KEY_DC:
                if editor.input_cursor < len(editor.input_value):
                    editor.input_value = (
                        editor.input_value[: editor.input_cursor]
                        + editor.input_value[editor.input_cursor + 1 :]
                    )
            elif isinstance(key, str) and key and all(char.isprintable() for char in key):
                editor.input_value = (
                    editor.input_value[: editor.input_cursor]
                    + key
                    + editor.input_value[editor.input_cursor :]
                )
                editor.input_cursor += len(key)
            return ()

        if editor.kind == "english_word" and editor.payload.get("moving_primary"):
            if key == curses.KEY_LEFT:
                editor.payload["stress_destination"] = max(
                    0, editor.payload["stress_destination"] - 1
                )
            elif key == curses.KEY_RIGHT:
                state: EnglishPhonemeEditorState = editor.payload["draft_state"]
                editor.payload["stress_destination"] = min(
                    len(state.vowel_stresses) - 1,
                    editor.payload["stress_destination"] + 1,
                )
            elif key in _ENTER_KEYS:
                return self._commit_primary_move()
            elif key == _ESCAPE:
                editor.payload.pop("moving_primary", None)
                editor.error = ""
            return ()

        if editor.kind == "settings" and key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            return self.adjust_settings(-1 if key == curses.KEY_LEFT else 1)
        if key == _ESCAPE:
            if editor.kind == "english_word":
                return self.cancel_word()
            return self.cancel()
        if key == curses.KEY_UP:
            return self.move_selection(-1)
        if key == curses.KEY_DOWN:
            return self.move_selection(1)
        if key in _ENTER_KEYS:
            return self._activate_selection(settings, query, current_source)
        return ()

    def _activate_selection(
        self,
        settings: Settings,
        query: AudioQuery | None,
        current_source: str | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        selected = editor.selection
        if editor.kind in {"text", "japanese"}:
            if selected == "draft":
                return self.begin_field("draft", editor.payload["draft"])
        elif editor.kind == "settings":
            if selected == "save_text":
                draft = editor.payload["draft_settings"]
                draft["save_text"] = not draft["save_text"]
            elif selected == "apply":
                return self.apply(settings, query, current_source)
            elif isinstance(selected, str):
                value = editor.payload["draft_settings"][selected]
                return self.begin_field(selected, str(value))
        elif editor.kind == "english_segment":
            if isinstance(selected, tuple) and selected[0] == "word":
                self._open_word_editor(selected[1])
            elif selected == "apply":
                return self.apply(settings, query, current_source)
            elif selected == "cancel":
                return self.cancel()
        elif editor.kind == "english_word":
            if selected == "phonemes":
                state = editor.payload["draft_state"]
                return self.begin_field("phonemes", " ".join(state.base_phonemes))
            if isinstance(selected, tuple) and selected[0] == "primary":
                state: EnglishPhonemeEditorState = editor.payload["draft_state"]
                positions = state.primary_stress_vowel_positions
                ordinal = selected[1]
                if ordinal is not None and ordinal < len(positions):
                    source = positions[ordinal]
                    editor.payload["moving_primary"] = True
                    editor.payload["stress_source"] = source
                    editor.payload["stress_destination"] = source
                    editor.error = "Choose a destination vowel with Left/Right, then Enter."
            elif selected == "done":
                return self._finish_word_editor()
            elif selected == "cancel":
                return self.cancel_word()
        return ()

    def _finish_field(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.active_field is None:
            return ()
        name = editor.active_field
        value = editor.input_value
        if editor.kind == "english_word" and name == "phonemes":
            try:
                current = editor.payload["draft_state"]
                updated = replace_editor_base_phonemes(current, value.split())
            except Exception as exc:
                editor.error = f"Error: {exc}"
                return ()
            editor.payload["draft_state"] = updated
            editor.input_value = " ".join(updated.base_phonemes)
            value = editor.input_value
        elif editor.kind == "settings":
            editor.payload["draft_settings"][name] = value
        else:
            editor.payload[name] = value
        editor.active_field = None
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = ""
        if editor.kind == "settings":
            status = "Settings field updated; Apply saves the settings draft."
        elif editor.kind == "english_word":
            status = "Phonemes updated in the word draft; Done returns it to the segment."
        else:
            status = "Draft field updated."
        return (UpdateStatusIntent(status),)

    def _open_word_editor(self, group_index: int | None) -> None:
        parent = self.editor
        if parent is None or group_index is None:
            return
        group: EnglishWordGroup = parent.payload["groups"][group_index]
        try:
            state = english_phonemes_to_editor_state(group.phonemes)
        except Exception as exc:
            parent.error = f"Error: Cannot edit token {group.label!r}: {exc}"
            return
        self.editor = EditorState(
            kind="english_word",
            title="EDIT ENGLISH WORD",
            origin=parent.origin,
            selection="phonemes",
            payload={
                "parent": parent,
                "group_index": group_index,
                "label": group.label,
                "source_text": parent.payload["source_text"],
                "draft_state": state,
                "moving_primary": False,
            },
        )

    def _commit_primary_move(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        state: EnglishPhonemeEditorState = editor.payload["draft_state"]
        source = editor.payload["stress_source"]
        destination = editor.payload["stress_destination"]
        occupied = state.primary_stress_vowel_positions
        if destination in occupied and destination != source:
            editor.error = "Error: That vowel already has primary stress. Choose another vowel."
            return ()
        if destination != source:
            try:
                state = move_primary_stress(state, source, destination)
            except Exception as exc:
                editor.error = f"Error: Primary stress was not changed: {exc}"
                return ()
            editor.payload["draft_state"] = state
        editor.payload.pop("moving_primary", None)
        positions = state.primary_stress_vowel_positions
        if destination in positions:
            editor.selection = ("primary", positions.index(destination))
        editor.error = ""
        return (UpdateStatusIntent("Word stress draft updated."),)

    def _finish_word_editor(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        parent: EditorState = editor.payload["parent"]
        index = editor.payload["group_index"]
        groups = list(parent.payload["groups"])
        old_group = groups[index]
        groups[index] = EnglishWordGroup(
            old_group.label,
            tuple(editor_state_to_english_phonemes(editor.payload["draft_state"])),
            old_group.editable,
        )
        parent.payload["groups"] = tuple(groups)
        parent.selection = ("word", index)
        parent.error = ""
        self.editor = parent
        return (
            UpdateStatusIntent(
                f"{old_group.label} draft updated; Apply changes to commit it."
            ),
        )

    def cancel_word(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        parent = editor.payload.get("parent")
        if parent is not None:
            self.editor = parent
            parent.error = ""
            return (UpdateStatusIntent("Word changes canceled."),)
        return ()

    def apply(
        self,
        settings: Settings,
        query: AudioQuery | None,
        current_source: str | None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.kind == "text":
            source = editor.payload["draft"]
            if current_source is not None and source == current_source:
                return self._close_editor("Source text unchanged.")
            return (ReplaceSourceTextIntent(source),)
        if editor.kind == "japanese":
            try:
                if query is None:
                    raise ValueError("There is no active utterance")
                updated = replace_japanese_pronunciation(
                    query,
                    editor.payload["draft"],
                    segment_index=editor.payload["segment_index"],
                )
            except Exception as exc:
                editor.error = f"Error: Pronunciation was not changed: {exc}"
                return ()
            return (
                ReplaceQueryIntent(
                    query=updated,
                    editor_kind="japanese",
                    success_status="Japanese pronunciation updated; old takes cleared.",
                ),
            )
        if editor.kind == "english_segment":
            index = editor.payload["segment_index"]
            groups: tuple[EnglishWordGroup, ...] = editor.payload["groups"]
            try:
                if query is None:
                    raise ValueError("There is no active utterance")
                updated = replace_english_phoneme_groups(
                    query,
                    segment_index=index,
                    phoneme_groups=tuple(group.phonemes for group in groups),
                )
            except Exception as exc:
                editor.error = f"Error: English changes were not applied: {exc}"
                return ()
            accepted_grouping = EnglishGroupingCache(
                editor.payload["source_text"], groups
            )
            return (
                ReplaceQueryIntent(
                    query=updated,
                    editor_kind="english_segment",
                    success_status="English pronunciation updated; old takes cleared.",
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
            updated = replace(
                settings,
                style_id=int(draft["style_id"]),
                speed=float(draft["speed"]),
                take_count=int(draft["take_count"]),
                output_dir=Path(draft["output_dir"]).expanduser(),
                save_text=bool(draft["save_text"]),
            )
        except (TypeError, ValueError, SettingsError) as exc:
            editor.error = f"Error: Settings were not changed: {exc}"
            return ()
        changes = {
            name: getattr(updated, name)
            for name in ("style_id", "speed", "take_count", "output_dir", "save_text")
            if getattr(updated, name) != getattr(settings, name)
        }
        if not changes:
            return self._close_editor("Settings unchanged.")
        return (
            ApplySettingsIntent(
                SettingsChanges(
                    style_id=changes.get("style_id"),
                    speed=changes.get("speed"),
                    take_count=changes.get("take_count"),
                    output_dir=changes.get("output_dir"),
                    save_text=changes.get("save_text"),
                )
            ),
        )

    def complete_query_application(
        self,
        intent: ReplaceQueryIntent,
        result: QueryApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if result.error is not None:
            if intent.editor_kind == "japanese":
                editor.error = f"Error: Pronunciation was not changed: {result.error}"
            else:
                editor.error = f"Error: English changes were not applied: {result.error}"
            return ()
        self.reconcile_groupings(intent.query)
        if intent.grouping_index is not None and intent.accepted_grouping is not None:
            self.grouping_cache[intent.grouping_index] = intent.accepted_grouping
        return self._close_editor(intent.success_status)

    def complete_source_text_application(
        self,
        result: SourceTextApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if result.error is not None:
            editor.error = f"Error: Source text was not changed: {result.error}"
            return ()
        if result.unchanged:
            return self._close_editor("Source text unchanged.")
        self.clear_groupings()
        status = (
            "Source text updated; rebuild pronunciation before generating."
            if result.needs_rebuild
            else "Source text updated; pronunciation preserved."
        )
        return self._close_editor(status)

    def complete_settings_application(
        self,
        result: SettingsApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if result.error_status is not None and result.error_status.startswith("Error:"):
            editor.error = result.error_status
            return ()
        return self._close_editor("Settings saved. Existing temporary takes were cleared.")

    def cancel(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        status = {
            "text": "Text draft discarded.",
            "japanese": "Japanese pronunciation draft discarded.",
            "settings": "Settings draft discarded.",
            "english_segment": "English segment draft discarded.",
        }.get(editor.kind, "Editor draft discarded.")
        return self._close_editor(status)

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
        if selected not in {"style_id", "speed", "take_count", "save_text"}:
            return ()
        clear_feedback = (ClearAdjustmentFeedbackIntent(),)
        feedback = AdjustmentPressedIntent("settings", selected, direction)
        if selected == "style_id":
            styles = self._available_styles()
            if not styles:
                editor.error = "Error: No available styles can be selected."
                return clear_feedback
            try:
                current_id = int(draft["style_id"])
            except (TypeError, ValueError):
                editor.error = "Error: Style ID must be a positive integer."
                return clear_feedback
            index = next(
                (i for i, style in enumerate(styles) if style.id == current_id),
                None,
            )
            if index is None:
                choices = [
                    style for style in styles
                    if (style.id > current_id if direction > 0 else style.id < current_id)
                ]
                if not choices:
                    return clear_feedback
                updated_id = choices[0 if direction > 0 else -1].id
            else:
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
                editor.error = "Error: Speed must be a positive finite number."
                return clear_feedback
            if updated == current:
                editor.error = ""
                return clear_feedback
            draft["speed"] = f"{updated:.2f}"
        elif selected == "take_count":
            try:
                current = int(draft["take_count"])
            except (TypeError, ValueError):
                editor.error = "Error: Take count must be an integer from 1 through 8."
                return clear_feedback
            updated = min(8, max(1, current + direction))
            if updated == current:
                editor.error = ""
                return clear_feedback
            draft["take_count"] = str(updated)
        elif selected == "save_text":
            updated = direction > 0
            if draft["save_text"] == updated:
                editor.error = ""
                return clear_feedback
            draft["save_text"] = updated
        editor.error = ""
        return (feedback,)
