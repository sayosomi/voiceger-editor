"""Editor facade coordinating focused TUI editor owners."""

from __future__ import annotations

import curses
from copy import deepcopy
from typing import Any, Callable, Sequence

from .settings import Settings
from .tui_confirmation import handle_confirmation_key
from .tui_display import _display_width
from .tui_editor_common import (
    AdjustmentPressedIntent,
    ApplyCaptionIntent,
    ApplySettingsIntent,
    BuildPronunciationIntent,
    BuildPronunciationResult,
    CaptionApplicationResult,
    ClearAdjustmentFeedbackIntent,
    ClearCandidatesIntent,
    CloseEditorIntent,
    EditorIntent,
    EditorState,
    OpenDictionaryIntent,
    OpenHelpIntent,
    PreviewIntent,
    QueryApplicationResult,
    QuitIntent,
    ReplaceQueryIntent,
    SaveToDictionaryIntent,
    SettingsApplicationResult,
    UpdateStatusIntent,
    adjustment_feedback_intents,
)
from .tui_editor_english import (
    EnglishGroupingCache,
    EnglishWordGroup,
    TuiEnglishEditorOwner,
)
from .tui_editor_pronunciation import (
    PronunciationRow,
    TuiPronunciationEditorOwner,
)
from .tui_editor_settings import TuiSettingsEditorOwner
from .tui_editor_text import TuiTextEditorOwner
from .tui_selection import move_clamped_selection
from .tui_shortcuts import menu_items, resolve_shortcut
from .tui_status import EMPTY_STATUS, error_status
from .tui_text_editing import apply_text_edit_key
from .voicevox_api_models import AudioQuery


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"


class TuiEditorController:
    """Compatibility facade over focused editor-family owners."""

    def __init__(
        self,
        *,
        english_word_groups: Callable[[str], Sequence[tuple[str, Sequence[str]]]],
        available_styles: Callable[[], Sequence[Any]],
        input_prefix: Callable[[EditorState], str],
    ) -> None:
        self.editor: EditorState | None = None
        self._english_word_groups = english_word_groups
        self._available_styles = available_styles
        self._input_prefix = input_prefix
        self._english = TuiEnglishEditorOwner(
            self,
            english_word_groups=english_word_groups,
        )
        self._settings = TuiSettingsEditorOwner(
            self,
            available_styles=available_styles,
        )
        self._text = TuiTextEditorOwner(self)
        self._pronunciation = TuiPronunciationEditorOwner(self)

    @property
    def grouping_cache(self) -> dict[int, EnglishGroupingCache]:
        return self._english.grouping_cache

    @grouping_cache.setter
    def grouping_cache(self, value: dict[int, EnglishGroupingCache]) -> None:
        self._english.grouping_cache = value

    @property
    def grouping_error(self):
        return self._english.grouping_error

    @grouping_error.setter
    def grouping_error(self, value) -> None:
        self._english.grouping_error = value

    def open_caption(self, *args, **kwargs):
        return self._text.open_caption(*args, **kwargs)

    def open_build_confirmation(
        self,
        *,
        origin: tuple[str, int | None],
    ) -> tuple[EditorIntent, ...]:
        self.editor = EditorState(
            kind="build_confirmation",
            title="REBUILD PRONUNCIATION?",
            origin=origin,
            selection="cancel",
            payload={
                "warning": "Manual pronunciation or utterance edits will be replaced."
            },
        )
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def open_settings(self, *args, **kwargs):
        return self._settings.open_settings(*args, **kwargs)

    def _settings_draft(self, *args, **kwargs):
        return self._settings._settings_draft(*args, **kwargs)

    def open_audio_output_settings(self, *args, **kwargs):
        return self._settings.open_audio_output_settings(*args, **kwargs)

    def _refresh_filename_preview(self, *args, **kwargs):
        return self._settings._refresh_filename_preview(*args, **kwargs)

    def open_add_section(self, *args, **kwargs):
        return self._text.open_add_section(*args, **kwargs)

    def open_section_text(self, *args, **kwargs):
        return self._text.open_section_text(*args, **kwargs)

    def pronunciation_rows(self, *args, **kwargs):
        return self._pronunciation.pronunciation_rows(*args, **kwargs)

    def open_pronunciation_item(self, *args, **kwargs):
        return self._pronunciation.open_pronunciation_item(*args, **kwargs)

    def english_grouping(self, *args, **kwargs):
        return self._english.english_grouping(*args, **kwargs)

    def adjust_pronunciation(self, *args, **kwargs):
        return self._pronunciation.adjust_pronunciation(*args, **kwargs)

    def reconcile_groupings(self, *args, **kwargs):
        return self._english.reconcile_groupings(*args, **kwargs)

    def remap_groupings_after_deletion(self, *args, **kwargs):
        return self._english.remap_groupings_after_deletion(*args, **kwargs)

    def clear_groupings(self, *args, **kwargs):
        return self._english.clear_groupings(*args, **kwargs)

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
        result = move_clamped_selection(
            editor.selection,
            self.selection_keys(),
            delta=delta,
        )
        if result is None or not result.changed:
            return ()
        editor.selection = result.selection
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

    def move_settings_section(self, direction: int) -> tuple[EditorIntent, ...]:
        return self._settings.move_settings_section(direction)

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
            if self._text.handle_active_field_key(key):
                return ()
            if key in _ENTER_KEYS:
                return self._finish_field()
            if key == _ESCAPE:
                if editor.kind in {
                    "caption",
                    "japanese",
                    "settings",
                    "english_word",
                    "section_text",
                    "add_section",
                }:
                    return self.cancel()
                editor.input_value = editor.input_original
                editor.input_cursor = len(editor.input_original)
                editor.active_field = None
                editor.error = EMPTY_STATUS
                if editor.kind == "audio_output_settings":
                    self._settings._refresh_filename_preview(
                        editor,
                        editor.input_original,
                    )
                return (UpdateStatusIntent(""),)
            if self._pronunciation.reject_active_key(key):
                return ()

            input_width = 1
            if key in (curses.KEY_UP, curses.KEY_DOWN):
                prefix = self._input_prefix(editor)
                input_width = max(
                    1,
                    screen_width - 1 - _display_width(prefix),
                )
            edit = apply_text_edit_key(
                editor.input_value,
                editor.input_cursor,
                key,
                input_width=input_width,
            )
            if edit.handled:
                editor.input_value = edit.value
                editor.input_cursor = edit.cursor
                if (
                    edit.text_changed
                    and editor.kind == "audio_output_settings"
                    and editor.active_field == "filename_template"
                ):
                    self._settings._refresh_filename_preview(editor, edit.value)
                    editor.error = EMPTY_STATUS
                elif edit.text_changed and editor.kind in {
                    "japanese",
                    "english_word",
                    "section_text",
                    "add_section",
                }:
                    editor.error = EMPTY_STATUS
            return ()

        if key in ("q", "Q", "\x03"):
            return (QuitIntent(),)
        if key == "?":
            return (OpenHelpIntent(),)

        if editor.kind in {
            "build_confirmation",
            "delete_confirmation",
            "clear_candidates_confirmation",
        }:
            interaction = handle_confirmation_key(
                editor.kind,
                str(editor.selection),
                key,
                editor.payload,
            )
            if interaction.handled:
                editor.selection = interaction.selection
                editor.error = EMPTY_STATUS
                if interaction.activation is not None:
                    return self._activate_selection(
                        settings,
                        query,
                        current_caption,
                    )
                if interaction.changed:
                    return (ClearAdjustmentFeedbackIntent(),)
                return ()

        if editor.kind == "settings":
            if key == "\t":
                return self._settings.move_settings_section(1)
            backtab = getattr(curses, "KEY_BTAB", None)
            if backtab is not None and key == backtab:
                return self._settings.move_settings_section(-1)

        shortcut = resolve_shortcut(editor.kind, key, editor.payload)
        if shortcut is not None:
            editor.selection = shortcut.key
            editor.error = EMPTY_STATUS
            if shortcut.shortcut_mode == "focus":
                return (ClearAdjustmentFeedbackIntent(),)
            return self._activate_selection(settings, query, current_caption)

        if editor.kind in {"settings", "audio_output_settings"} and key in (
            curses.KEY_LEFT,
            curses.KEY_RIGHT,
        ):
            return self._settings.adjust_settings(
                -1 if key == curses.KEY_LEFT else 1
            )

        if (
            editor.kind == "add_section"
            and editor.selection == "language"
            and key in (curses.KEY_LEFT, curses.KEY_RIGHT)
        ):
            return self._text.adjust_add_section_language(
                -1 if key == curses.KEY_LEFT else 1
            )

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

        if editor.kind in {"caption", "section_text", "add_section"}:
            return self._text.activate_selection(query, current_caption)

        if editor.kind in {"japanese", "english_word"}:
            return self._pronunciation.activate_selection(query)

        if editor.kind in {"settings", "audio_output_settings"}:
            return self._settings.activate_selection(settings, current_caption)

        selected = editor.selection
        if editor.kind == "build_confirmation":
            if selected == "rebuild":
                return (BuildPronunciationIntent(),)
            if selected == "cancel":
                return self._close_editor("Pronunciation rebuild cancelled.")

        if editor.kind == "delete_confirmation":
            if selected == "delete":
                return self._text.delete_section(query)
            if selected == "cancel":
                return self._restore_parent_editor(
                    "Section deletion cancelled."
                )

        if editor.kind == "clear_candidates_confirmation":
            if selected == "clear":
                origin = editor.origin
                self.editor = None
                return (
                    ClearCandidatesIntent(),
                    ClearAdjustmentFeedbackIntent(),
                    CloseEditorIntent(origin, "Candidates cleared."),
                )
            if selected == "cancel":
                return self._close_editor(
                    "Candidate clearing cancelled."
                )
        return ()

    def _set_caption_draft(self, *args, **kwargs):
        return self._text._set_caption_draft(*args, **kwargs)

    def _set_pronunciation_draft(self, *args, **kwargs):
        return self._pronunciation._set_pronunciation_draft(*args, **kwargs)

    def _set_text_draft(self, *args, **kwargs):
        return self._text._set_text_draft(*args, **kwargs)

    def _word_group_values(self, *args, **kwargs):
        return self._text._word_group_values(*args, **kwargs)

    def _grouping_cache(self, *args, **kwargs):
        return self._text._grouping_cache(*args, **kwargs)

    def _validated_text(self, *args, **kwargs):
        return self._text._validated_text(*args, **kwargs)

    def preview_section_text(self, *args, **kwargs):
        return self._text.preview_section_text(*args, **kwargs)

    def apply_section_text(self, *args, **kwargs):
        return self._text.apply_section_text(*args, **kwargs)

    def open_delete_confirmation(self, *args, **kwargs):
        return self._text.open_delete_confirmation(*args, **kwargs)

    def open_clear_candidates_confirmation(
        self,
        *,
        origin: tuple[str, int | None],
    ) -> tuple[EditorIntent, ...]:
        self.editor = EditorState(
            kind="clear_candidates_confirmation",
            title="CLEAR CANDIDATES?",
            origin=origin,
            selection="cancel",
            payload={
                "warning": (
                    "All generated candidate WAV files will be discarded."
                ),
            },
        )
        return (ClearAdjustmentFeedbackIntent(), UpdateStatusIntent(""))

    def delete_section(self, *args, **kwargs):
        return self._text.delete_section(*args, **kwargs)

    def add_section(self, *args, **kwargs):
        return self._text.add_section(*args, **kwargs)

    def preview(self, *args, **kwargs):
        return self._pronunciation.preview(*args, **kwargs)

    def _finish_field(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.active_field is None:
            return ()
        if editor.kind in {"settings", "audio_output_settings"}:
            return self._settings.finish_field()
        if editor.kind in {"japanese", "english_word"}:
            return self._pronunciation.finish_field()

        name = editor.active_field
        value = editor.input_value
        editor.payload[name] = value
        editor.active_field = None
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = EMPTY_STATUS
        return (UpdateStatusIntent(""),)

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
            return self._text.apply_caption(current_caption)
        if editor.kind in {"japanese", "english_word"}:
            return self._pronunciation.apply_pronunciation(query)
        if editor.kind == "settings":
            return self._settings._apply_settings(settings)
        return ()

    def _apply_settings(self, *args, **kwargs):
        return self._settings._apply_settings(*args, **kwargs)

    def complete_query_application(
        self,
        intent: ReplaceQueryIntent,
        result: QueryApplicationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if result.error is not None:
            if editor is None:
                return (
                    UpdateStatusIntent(
                        error_status(
                            f"Query was not changed: {result.error}"
                        )
                    ),
                )
            error_prefix = {
                "japanese": "Pronunciation was not changed",
                "english_word": "English pronunciation was not changed",
                "section_text": "Section text was not changed",
                "add_section": "Section was not added",
                "delete_section": "Section was not deleted",
            }.get(intent.editor_kind, "Query was not changed")
            editor.error = error_status(
                f"{error_prefix}: {result.error}"
            )
            return ()

        if intent.deleted_segment_index is not None:
            self._english.remap_groupings_after_deletion(
                intent.deleted_segment_index,
                intent.query,
            )
        else:
            self._english.reconcile_groupings(intent.query)

        if (
            intent.grouping_index is not None
            and intent.accepted_grouping is not None
        ):
            self._english.grouping_cache[
                intent.grouping_index
            ] = intent.accepted_grouping

        if not intent.close_editor:
            return (UpdateStatusIntent(intent.success_status),)
        if editor is None:
            return ()
        return self._close_editor(intent.success_status)

    def complete_caption_application(self, *args, **kwargs):
        return self._text.complete_caption_application(*args, **kwargs)

    def complete_build_confirmation(
        self,
        result: BuildPronunciationResult,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if result.error is not None:
            if editor is None:
                return (
                    UpdateStatusIntent(
                        error_status(
                            f"Pronunciation was not rebuilt: {result.error}"
                        )
                    ),
                )
            editor.error = error_status(
                f"Pronunciation was not rebuilt: {result.error}"
            )
            return ()
        self.editor = None
        return (ClearAdjustmentFeedbackIntent(),)

    def complete_settings_application(self, *args, **kwargs):
        return self._settings.complete_settings_application(*args, **kwargs)

    def cancel(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.kind == "audio_output_settings":
            return self._restore_parent_editor("")
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

    def _restore_parent_editor(
        self,
        status: str,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        parent = editor.payload.get("parent_editor")
        if not isinstance(parent, EditorState):
            return self._close_editor(status)
        self.editor = parent
        return (
            ClearAdjustmentFeedbackIntent(),
            UpdateStatusIntent(status),
        )

    def _close_editor(
        self,
        status,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        origin = editor.origin
        self.editor = None
        return (
            ClearAdjustmentFeedbackIntent(),
            CloseEditorIntent(origin, status),
        )

    def adjust_settings(self, *args, **kwargs):
        return self._settings.adjust_settings(*args, **kwargs)
