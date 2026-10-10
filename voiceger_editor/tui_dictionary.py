"""Keyboard-first TUI state and policy for user dictionary management."""

from __future__ import annotations

import curses
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Literal, Sequence, Union

from .dictionary_export import (
    export_voiceger_editor_dictionaries,
    export_voicevox_dictionary,
)

from .tui_adjustments import step_cyclic
from .tui_confirmation import handle_confirmation_key
from .tui_dictionary_list import (
    ENGLISH_SORT_MODES,
    JAPANESE_SORT_MODES,
    JAPANESE_WORD_TYPE_FILTERS,
    DictionaryListStateOwner,
    DictionaryListView,
    EnglishDictionarySort,
    JapaneseDictionarySort,
    JapaneseWordTypeFilter,
)
from .tui_display import _display_width
from .tui_editors import (
    AdjustmentPressedIntent,
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    adjustment_feedback_intents,
    EditorState,
    OpenHelpIntent,
    PreviewIntent,
    QuitIntent,
    UpdateStatusIntent,
)
from .tui_dictionary_entry import (
    DictionaryEntryOwner,
    _english_preview_query,
    _japanese_preview_query,
    _reading_morae,
)
from .tui_dictionary_accent import JapaneseListAccentOwner
from .tui_dictionary_import import DictionaryImportOwner
from .tui_dictionary_operations import (
    DictionaryLanguage,
    DictionaryOperationIdentity,
    DictionaryOperationIntent,
    DictionaryOperationRequest,
    dictionary_operation_request,
)
from .tui_output_path import BeginOutputPathEditIntent
from .tui_numbered_list import NumberedListJump
from .tui_selection import move_clamped_selection
from .tui_shortcuts import menu_items, resolve_shortcut
from .tui_status import EMPTY_STATUS, error_status, info_status, warning_status
from .tui_text_editing import apply_text_edit_key
from .user_dictionary import JapaneseWordType, UserDictionaryCore


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"
DictionaryControllerIntent = Union[
    EditorIntent,
    DictionaryOperationIntent,
    BeginOutputPathEditIntent,
]


class TuiDictionaryController:
    """Own dictionary modal state while leaving the caller editor untouched."""

    def __init__(
        self,
        core: UserDictionaryCore,
        *,
        input_prefix,
        japanese_pronunciation: Callable[[str], Any] | None = None,
        english_word_groups: Callable[[str], Sequence[tuple[str, Sequence[str]]]]
        | None = None,
        output_dir: Callable[[], Path] | None = None,
    ) -> None:
        self.core = core
        self.editor: EditorState | None = None
        self._stack: list[EditorState] = []
        self._input_prefix = input_prefix
        self._japanese_pronunciation = japanese_pronunciation
        self._english_word_groups = english_word_groups
        self._output_dir = output_dir or (lambda: Path("."))
        self._list_state = DictionaryListStateOwner(core)
        self._accent = JapaneseListAccentOwner(core)
        self._deferred_list_key: Any | None = None
        self._number_jump = NumberedListJump()
        self._import_owner = DictionaryImportOwner(
            core,
            get_editor=lambda: self.editor,
            set_editor=lambda value: setattr(self, "editor", value),
            parent_stack=self._stack,
            output_dir=self._output_dir,
            menu_state=self._menu_state,
        )
        self._entry_owner = DictionaryEntryOwner(
            core,
            get_editor=lambda: self.editor,
            set_editor=lambda value: setattr(self, "editor", value),
            parent_stack=self._stack,
            get_japanese_pronunciation=lambda: self._japanese_pronunciation,
            get_english_word_groups=lambda: self._english_word_groups,
            list_state=self._list_state,
            remember_list_focus=self._remember_list_focus,
            japanese_list_state=self._japanese_list_state,
            english_list_state=self._english_list_state,
            menu_state=self._menu_state,
        )

    @property
    def active(self) -> bool:
        return self.editor is not None

    def open_menu(
        self,
        *,
        preserve_current: bool = False,
    ) -> tuple[EditorIntent, ...]:
        if preserve_current and self.editor is not None:
            self._stack.append(deepcopy(self.editor))
        else:
            self._stack.clear()
        self.editor = self._menu_state()
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _menu_state(self) -> EditorState:
        return EditorState(
            kind="dictionary_menu",
            title="DICTIONARY",
            origin=("dictionary", None),
            selection="japanese",
            payload={
                "japanese_count": len(self.core.list_japanese_entries()),
                "english_count": len(self.core.list_english_entries()),
            },
        )

    @staticmethod
    def _export_state() -> EditorState:
        return EditorState(
            kind="dictionary_export",
            title="EXPORT DICTIONARY",
            origin=("dictionary", None),
            selection="voiceger",
            payload={},
        )

    def _export_dictionary(
        self,
        target: Literal["voiceger", "voicevox"],
    ) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()

        core = self.core
        output_dir = Path(self._output_dir())
        if target == "voiceger":
            operation: DictionaryOperationIdentity = "export_voiceger_editor"
            status = "Exporting Voiceger Editor dictionaries…"

            def work() -> Any:
                return export_voiceger_editor_dictionaries(core, output_dir)
        else:
            operation = "export_voicevox"
            status = "Exporting VOICEVOX dictionary…"

            def work() -> Any:
                return export_voicevox_dictionary(core, output_dir)

        request = dictionary_operation_request(
            editor,
            operation=operation,
            language=None,
        )
        return (
            DictionaryOperationIntent(
                request,
                info_status(status),
                work,
            ),
        )

    def open_quick_save_japanese(
        self,
        *,
        surface: str,
        pronunciation: str,
    ) -> tuple[EditorIntent, ...]:
        """Keep the Dictionary quick-save entrypoint for TuiApp callers."""

        return self._entry_owner.open_quick_save_japanese(
            surface=surface,
            pronunciation=pronunciation,
        )

    def open_quick_save_english(
        self,
        *,
        surface: str,
        phonemes: str,
    ) -> tuple[EditorIntent, ...]:
        """Keep the Dictionary quick-save entrypoint for TuiApp callers."""

        return self._entry_owner.open_quick_save_english(
            surface=surface,
            phonemes=phonemes,
        )

    def _restore_parent(self) -> None:
        if not self._stack:
            self.editor = None
            return
        parent = self._stack.pop()
        if parent.kind == "dictionary_menu":
            refreshed = self._menu_state()
            refreshed.selection = parent.selection
            self.editor = refreshed
        else:
            self.editor = parent

    @property
    def has_unsaved_list_accents(self) -> bool:
        return self._accent.has_pending

    def defer_quit_for_accents(self) -> tuple[EditorIntent, ...]:
        """Request a save before quitting; completion resumes Quit."""
        if not self._accent.has_pending:
            return (QuitIntent(),)
        self._deferred_list_key = "q"
        self._accent.force_save()
        return (UpdateStatusIntent(info_status("Saving dictionary accents before quitting…")),)

    def pending_accent_commit(
        self, *, operation_busy: bool, now: float | None = None
    ) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        request = self._accent.begin(editor, operation_busy=operation_busy, now=now)
        return (request,) if request is not None else ()

    def _list_payload(self, view: DictionaryListView) -> dict[str, Any]:
        is_japanese = view.word_type_filter is not None
        return {
            "entries": self._accent.overlay(view.entries) if is_japanese else view.entries,
            "accent_pending": is_japanese and self._accent.has_pending,
            "accent_saving": is_japanese and self._accent.inflight is not None,
            "entry_ids": view.identities,
            "entry_index": view.focused_index,
            "sort_mode": view.sort_mode,
            "text_filter": view.text_query,
            "filter_enabled": view.filter_enabled,
            "word_type_filter": view.word_type_filter,
            "visible_count": view.shown_count,
            "total_count": view.total_count,
            "can_delete": bool(view.entries),
            "number_jump_active": self._number_jump.active,
            "number_jump_value": self._number_jump.value,
        }

    def _sync_number_jump_payload(self, editor: EditorState) -> None:
        if editor.kind not in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            return
        editor.payload["number_jump_active"] = self._number_jump.active
        editor.payload["number_jump_value"] = self._number_jump.value

    def _open_list_entry_number(
        self,
        target_number: int,
    ) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind not in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            return ()
        target_index = target_number - 1
        entries = tuple(editor.payload.get("entries", ()))
        if not 0 <= target_index < len(entries):
            return ()
        editor.selection = ("entry", target_index)
        editor.payload["entry_index"] = target_index
        editor.error = EMPTY_STATUS
        self._remember_list_focus(editor)
        return self._activate()

    @staticmethod
    def _focused_list_identity(editor: EditorState) -> str | None:
        identities = tuple(editor.payload.get("entry_ids", ()))
        index = None
        if (
            isinstance(editor.selection, tuple)
            and editor.selection[0] == "entry"
            and isinstance(editor.selection[1], int)
        ):
            index = editor.selection[1]
        elif isinstance(editor.payload.get("entry_index"), int):
            index = editor.payload["entry_index"]
        if index is None or not 0 <= index < len(identities):
            return None
        return str(identities[index])

    def _remember_list_focus(self, editor: EditorState) -> str | None:
        identity = self._focused_list_identity(editor)
        if identity is None:
            return None
        if editor.kind == "dictionary_japanese_list":
            self._list_state.remember_focus("ja", identity)
        elif editor.kind == "dictionary_english_list":
            self._list_state.remember_focus("en", identity)
        return identity

    def _japanese_list_state(self) -> EditorState:
        self._number_jump.reset()
        view = self._list_state.japanese_view()
        return EditorState(
            kind="dictionary_japanese_list",
            title="JAPANESE DICTIONARY",
            origin=("dictionary", None),
            selection=(
                ("entry", view.focused_index)
                if view.focused_index is not None
                else "add"
            ),
            payload=self._list_payload(view),
        )

    def _english_list_state(self) -> EditorState:
        self._number_jump.reset()
        view = self._list_state.english_view()
        return EditorState(
            kind="dictionary_english_list",
            title="ENGLISH DICTIONARY",
            origin=("dictionary", None),
            selection=(
                ("entry", view.focused_index)
                if view.focused_index is not None
                else "add"
            ),
            payload=self._list_payload(view),
        )

    def set_japanese_list_sort(self, sort_mode: JapaneseDictionarySort) -> None:
        editor = self.editor
        if editor is not None and editor.kind == "dictionary_japanese_list":
            self._remember_list_focus(editor)
        self._list_state.set_japanese_sort(sort_mode)
        if editor is not None and editor.kind == "dictionary_japanese_list":
            self.editor = self._japanese_list_state()

    def set_english_list_sort(self, sort_mode: EnglishDictionarySort) -> None:
        editor = self.editor
        if editor is not None and editor.kind == "dictionary_english_list":
            self._remember_list_focus(editor)
        self._list_state.set_english_sort(sort_mode)
        if editor is not None and editor.kind == "dictionary_english_list":
            self.editor = self._english_list_state()

    def set_japanese_list_filter(
        self,
        *,
        text_query: str,
        word_type_filter: JapaneseWordTypeFilter,
    ) -> None:
        editor = self.editor
        if editor is not None and editor.kind == "dictionary_japanese_list":
            self._remember_list_focus(editor)
        self._list_state.set_japanese_filter(
            text_query=text_query,
            word_type_filter=word_type_filter,
        )
        if editor is not None and editor.kind == "dictionary_japanese_list":
            self.editor = self._japanese_list_state()

    def set_english_list_filter(self, *, text_query: str) -> None:
        editor = self.editor
        if editor is not None and editor.kind == "dictionary_english_list":
            self._remember_list_focus(editor)
        self._list_state.set_english_filter(text_query=text_query)
        if editor is not None and editor.kind == "dictionary_english_list":
            self.editor = self._english_list_state()

    def _cycle_list_sort(
        self,
        direction: int = 1,
        *,
        show_feedback: bool = False,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        if editor.kind == "dictionary_japanese_list":
            modes = JAPANESE_SORT_MODES
            current = editor.payload["sort_mode"]
            result = step_cyclic(current, modes, direction=direction)
            if not result.changed:
                editor.selection = "sort"
                return adjustment_feedback_intents(
                    changed=False,
                    area="dictionary",
                    control="sort",
                    direction=direction,
                )
            self.set_japanese_list_sort(result.value)
        elif editor.kind == "dictionary_english_list":
            modes = ENGLISH_SORT_MODES
            current = editor.payload["sort_mode"]
            result = step_cyclic(current, modes, direction=direction)
            if not result.changed:
                editor.selection = "sort"
                return adjustment_feedback_intents(
                    changed=False,
                    area="dictionary",
                    control="sort",
                    direction=direction,
                )
            self.set_english_list_sort(result.value)
        else:
            return ()
        assert self.editor is not None
        self.editor.selection = "sort"
        if show_feedback:
            return (
                UpdateStatusIntent(""),
                *adjustment_feedback_intents(
                    changed=True,
                    area="dictionary",
                    control="sort",
                    direction=direction,
                ),
            )
        return (
            UpdateStatusIntent(""),
            *adjustment_feedback_intents(
                changed=False,
                area="dictionary",
                control="sort",
                direction=direction,
            ),
        )

    def _open_sort_editor(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind not in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            return ()
        self._remember_list_focus(editor)
        language: DictionaryLanguage = (
            "ja" if editor.kind == "dictionary_japanese_list" else "en"
        )
        modes = JAPANESE_SORT_MODES if language == "ja" else ENGLISH_SORT_MODES
        current = editor.payload["sort_mode"]
        self._stack.append(deepcopy(editor))
        self.editor = EditorState(
            kind="dictionary_sort",
            title=(
                "SORT JAPANESE DICTIONARY"
                if language == "ja"
                else "SORT ENGLISH DICTIONARY"
            ),
            origin=("dictionary", None),
            selection=("sort", modes.index(current)),
            payload={
                "language": language,
                "modes": modes,
            },
        )
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _choose_sort(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind != "dictionary_sort":
            return ()
        selected = editor.selection
        if selected == "back":
            self._restore_parent()
            return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())
        if (
            not isinstance(selected, tuple)
            or selected[0] != "sort"
            or not isinstance(selected[1], int)
        ):
            return ()
        modes = tuple(editor.payload["modes"])
        if not 0 <= selected[1] < len(modes):
            return ()
        target = modes[selected[1]]
        language: DictionaryLanguage = editor.payload["language"]
        if self._stack:
            self._stack.pop()
        if language == "ja":
            self._list_state.set_japanese_sort(target)
            self.editor = self._japanese_list_state()
        else:
            self._list_state.set_english_sort(target)
            self.editor = self._english_list_state()
        assert self.editor is not None
        self.editor.selection = "sort"
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    @staticmethod
    def _list_filter_has_criteria(editor: EditorState) -> bool:
        text_query = str(editor.payload.get("text_filter", "")).strip()
        if editor.kind == "dictionary_japanese_list":
            return (
                bool(text_query)
                or str(editor.payload.get("word_type_filter") or "ALL") != "ALL"
            )
        if editor.kind == "dictionary_english_list":
            return bool(text_query)
        return False

    def _set_list_filter_enabled(
        self,
        enabled: bool,
        direction: int,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind not in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            return ()
        if not self._list_filter_has_criteria(editor):
            editor.selection = "filter"
            return adjustment_feedback_intents(
                changed=False,
                area="dictionary",
                control="filter",
                direction=direction,
            )
        if bool(editor.payload.get("filter_enabled")) == enabled:
            editor.selection = "filter"
            return adjustment_feedback_intents(
                changed=False,
                area="dictionary",
                control="filter",
                direction=direction,
            )
        self._remember_list_focus(editor)
        if editor.kind == "dictionary_japanese_list":
            self._list_state.set_japanese_filter_enabled(enabled)
            self.editor = self._japanese_list_state()
        else:
            self._list_state.set_english_filter_enabled(enabled)
            self.editor = self._english_list_state()
        assert self.editor is not None
        self.editor.selection = "filter"
        return (
            UpdateStatusIntent(""),
            *adjustment_feedback_intents(
                changed=True,
                area="dictionary",
                control="filter",
                direction=direction,
            ),
        )

    def _open_filter_editor(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind not in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            return ()
        self._remember_list_focus(editor)
        self._stack.append(deepcopy(editor))
        if editor.kind == "dictionary_japanese_list":
            self.editor = EditorState(
                kind="dictionary_japanese_filter",
                title="FILTER JAPANESE DICTIONARY",
                origin=("dictionary", None),
                selection="text_query",
                payload={
                    "language": "ja",
                    "text_query": editor.payload["text_filter"],
                    "word_type_filter": editor.payload["word_type_filter"],
                },
            )
        else:
            self.editor = EditorState(
                kind="dictionary_english_filter",
                title="FILTER ENGLISH DICTIONARY",
                origin=("dictionary", None),
                selection="text_query",
                payload={
                    "language": "en",
                    "text_query": editor.payload["text_filter"],
                },
            )
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _finish_filter(
        self,
        *,
        clear: bool = False,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind not in {
            "dictionary_japanese_filter",
            "dictionary_english_filter",
        }:
            return ()
        language: DictionaryLanguage = editor.payload["language"]
        if self._stack:
            expected = (
                "dictionary_japanese_list"
                if language == "ja"
                else "dictionary_english_list"
            )
            if self._stack[-1].kind == expected:
                self._stack.pop()
        if language == "ja":
            self._list_state.set_japanese_filter(
                text_query="" if clear else str(editor.payload["text_query"]),
                word_type_filter=(
                    "ALL" if clear else editor.payload["word_type_filter"]
                ),
            )
            self.editor = self._japanese_list_state()
        else:
            self._list_state.set_english_filter(
                text_query="" if clear else str(editor.payload["text_query"]),
            )
            self.editor = self._english_list_state()
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _adjust_filter(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if (
            editor is None
            or editor.kind != "dictionary_japanese_filter"
            or editor.selection != "word_type"
        ):
            return ()
        current = editor.payload["word_type_filter"]
        result = step_cyclic(current, JAPANESE_WORD_TYPE_FILTERS, direction=direction)
        editor.payload["word_type_filter"] = result.value
        return adjustment_feedback_intents(
            changed=result.changed,
            area="dictionary",
            control="word_type",
            direction=direction,
        )

    def _begin_field(self, name: str, value: str) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        editor.selection = name
        editor.active_field = name
        editor.input_value = value
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = EMPTY_STATUS
        return (ClearAdjustmentFeedbackIntent(),)

    def _finish_field(self) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None or editor.active_field is None:
            return ()
        if editor.kind in {
            "dictionary_japanese_entry",
            "dictionary_english_entry",
        }:
            return self._entry_owner._finish_field()

        name = editor.active_field
        value = editor.input_value
        try:
            if (
                editor.kind
                in {
                    "dictionary_japanese_filter",
                    "dictionary_english_filter",
                }
                and name == "text_query"
            ):
                editor.payload["text_query"] = value
            elif editor.kind == "dictionary_import_path" and name == "path":
                editor.payload["path"] = value
        except Exception as exc:
            editor.error = error_status(f"{exc}")
            return ()
        editor.active_field = None
        editor.input_original = editor.input_value
        editor.error = EMPTY_STATUS
        return (UpdateStatusIntent(""),)

    def _move_dynamic_selection(self, delta: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()

        def apply_movement(keys: Sequence[Any]) -> None:
            result = move_clamped_selection(editor.selection, keys, delta=delta)
            if result is not None:
                editor.selection = result.selection

        if editor.kind in {
            "dictionary_menu",
            "dictionary_export",
        }:
            apply_movement(
                [item.key for item in menu_items(editor.kind, editor.payload)]
            )
            return ()
        if editor.kind == "dictionary_import_path":
            apply_movement(
                [item.key for item in menu_items(editor.kind, editor.payload)]
            )
            return ()
        if editor.kind == "dictionary_import_review":
            entries = tuple(editor.payload["items"])
            entry_keys = [("import_entry", index) for index in range(len(entries))]
            action_keys = [item.key for item in menu_items(editor.kind, editor.payload)]
            apply_movement([*entry_keys, *action_keys])
            return ()
        if editor.kind in {
            "dictionary_import_japanese_detail",
            "dictionary_import_english_detail",
        }:
            apply_movement(
                [item.key for item in menu_items(editor.kind, editor.payload)]
            )
            return ()
        if editor.kind in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            entries = editor.payload["entries"]
            entry_keys = [("entry", index) for index in range(len(entries))]
            action_keys = [item.key for item in menu_items(editor.kind, editor.payload)]
            apply_movement([*entry_keys, *action_keys])
            if (
                isinstance(editor.selection, tuple)
                and editor.selection[0] == "entry"
                and editor.selection[1] is not None
            ):
                editor.payload["entry_index"] = editor.selection[1]
                self._remember_list_focus(editor)
            return ()
        if editor.kind == "dictionary_sort":
            modes = tuple(editor.payload["modes"])
            apply_movement(
                [
                    *(("sort", index) for index in range(len(modes))),
                    "back",
                ]
            )
            return ()
        if editor.kind in {
            "dictionary_japanese_filter",
            "dictionary_english_filter",
        }:
            apply_movement(
                [item.key for item in menu_items(editor.kind, editor.payload)]
            )
            return ()
        if editor.kind == "dictionary_japanese_duplicates":
            self._entry_owner.move_duplicate_selection(editor, delta)
            return ()
        return ()

    def _complete_list_accent_operation(
        self, error: BaseException | None,
    ) -> tuple[DictionaryControllerIntent, ...]:
        self._accent.complete(error)
        editor = self.editor
        if editor is not None and editor.kind == "dictionary_japanese_list":
            previous_selection = editor.selection
            self._remember_list_focus(editor)
            self.editor = self._japanese_list_state()
            if isinstance(previous_selection, str):
                self.editor.selection = previous_selection
        if error is not None:
            self._deferred_list_key = None
            return (
                UpdateStatusIntent(error_status(
                    f"Japanese dictionary accents were not saved; restored previous values: {error}"
                )),
                ClearAdjustmentFeedbackIntent(),
            )
        if self._accent.has_pending:
            if self._deferred_list_key is not None:
                self._accent.force_save()
            return (UpdateStatusIntent(info_status("Saving newer accent changes…")),)
        key = self._deferred_list_key
        self._deferred_list_key = None
        if key is not None:
            return self.handle_key(key)
        return (UpdateStatusIntent(info_status("Japanese dictionary accents saved.")),)

    def complete_operation(
        self,
        request: DictionaryOperationRequest,
        value: Any = None,
        error: BaseException | None = None,
    ) -> tuple[DictionaryControllerIntent, ...]:
        """Route worker results to the owner of the originating Dictionary flow."""

        if request.operation == "save_japanese_list_accents":
            return self._complete_list_accent_operation(error)

        editor = self.editor
        if editor is not request.originating_editor:
            # Work may finish after another Dictionary surface replaced its origin.
            return (UpdateStatusIntent(""),)

        if request.operation in {
            "load_dictionary_import",
            "commit_dictionary_import",
        }:
            return self._import_owner.complete_operation(request, value, error)
        if request.operation in {
            "generate_japanese_pronunciation",
            "generate_english_pronunciation",
            "save_japanese",
            "save_english",
            "delete_japanese",
            "delete_english",
        }:
            return self._entry_owner.complete_operation(request, value, error)

        assert editor is not None
        if error is not None:
            editor.error = error_status(f"Dictionary export was not completed: {error}")
            return (UpdateStatusIntent(editor.error),)

        editor.error = EMPTY_STATUS
        filenames = ", ".join(path.name for path in value.paths)
        return (
            UpdateStatusIntent(f"Dictionary export complete: {filenames}"),
            ClearAdjustmentFeedbackIntent(),
        )

    def _activate(self) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        selected = editor.selection
        if editor.kind == "dictionary_menu":
            if selected == "japanese":
                self._stack.append(deepcopy(editor))
                self.editor = self._japanese_list_state()
            elif selected == "english":
                self._stack.append(deepcopy(editor))
                self.editor = self._english_list_state()
            elif selected == "import":
                self._stack.append(deepcopy(editor))
                self._import_owner._clear_import_state()
                self.editor = self._import_owner._import_path_state()
                return self._begin_field(
                    "path",
                    str(self.editor.payload["path"]),
                )
            elif selected == "export":
                self._stack.append(deepcopy(editor))
                self.editor = self._export_state()
            elif selected == "back":
                self._restore_parent()
            return (UpdateStatusIntent(""),)
        if editor.kind == "dictionary_export":
            if selected == "output":
                return (BeginOutputPathEditIntent("dictionary_export"),)
            if selected == "voiceger":
                return self._export_dictionary("voiceger")
            if selected == "voicevox":
                return self._export_dictionary("voicevox")
            if selected == "back":
                self._restore_parent()
                return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())
            return ()
        if editor.kind == "dictionary_import_path":
            if selected == "path":
                return self._begin_field(
                    "path",
                    str(editor.payload.get("path", "")),
                )
            if selected == "review":
                return self._import_owner._load_dictionary_import()
            if selected == "back":
                self._import_owner._clear_import_state()
                self._restore_parent()
                return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())
            return ()
        if editor.kind == "dictionary_import_review":
            if selected == "import_selected":
                return self._import_owner._commit_dictionary_import()
            if selected == "clear_selection":
                return self._import_owner._clear_import_selection()
            if selected == "back":
                self._import_owner._clear_import_state()
                self._restore_parent()
                return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())
            if (
                isinstance(selected, tuple)
                and selected[0] == "import_entry"
                and isinstance(selected[1], int)
            ):
                self.editor = self._import_owner._import_detail_state(selected[1])
                return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())
            return ()
        if editor.kind in {
            "dictionary_import_japanese_detail",
            "dictionary_import_english_detail",
        }:
            if selected == "back":
                return self._import_owner._back_from_import_detail()
            return ()
        if editor.kind == "dictionary_japanese_list":
            if selected == "preview":
                return self._preview_list_word(allow_action=True)
            if selected == "sort":
                return self._open_sort_editor()
            if selected == "filter":
                return self._open_filter_editor()
            if selected == "add":
                self._stack.append(deepcopy(editor))
                self.editor = self._entry_owner._japanese_entry_state(
                    word_uuid=None,
                    word=None,
                )
                return self._begin_field("surface", "")
            if selected == "delete":
                return self._entry_owner._open_delete_confirmation()
            if selected == "back":
                self._restore_parent()
                return (UpdateStatusIntent(""),)
            if isinstance(selected, tuple) and selected[0] == "entry":
                self._entry_owner.open_selected_list_entry(editor)
                return ()
        if editor.kind == "dictionary_english_list":
            if selected == "preview":
                return self._preview_list_word(allow_action=True)
            if selected == "sort":
                return self._open_sort_editor()
            if selected == "filter":
                return self._open_filter_editor()
            if selected == "add":
                self._stack.append(deepcopy(editor))
                self.editor = self._entry_owner._english_entry_state()
                return self._begin_field("surface", "")
            if selected == "delete":
                return self._entry_owner._open_delete_confirmation()
            if selected == "back":
                self._restore_parent()
                return (UpdateStatusIntent(""),)
            if isinstance(selected, tuple) and selected[0] == "entry":
                self._entry_owner.open_selected_list_entry(editor)
                return ()
        if editor.kind == "dictionary_sort":
            return self._choose_sort()
        if editor.kind in {
            "dictionary_japanese_filter",
            "dictionary_english_filter",
        }:
            if selected == "text_query":
                return self._begin_field(
                    "text_query",
                    str(editor.payload["text_query"]),
                )
            if selected == "apply":
                return self._finish_filter()
            if selected == "clear":
                return self._finish_filter(clear=True)
            if selected == "back":
                self._restore_parent()
                return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())
            return ()
        if editor.kind == "dictionary_japanese_duplicates":
            if isinstance(selected, tuple) and selected[0] == "entry":
                self._entry_owner.select_duplicate_entry(editor, selected[1])
                return ()
        if editor.kind == "dictionary_japanese_entry":
            if selected == "surface":
                return self._begin_field("surface", editor.payload["surface"])
            if selected == "pronunciation":
                return self._begin_field(
                    "pronunciation", editor.payload["pronunciation"]
                )
            if selected == "generate_pronunciation":
                return self._entry_owner._generate_pronunciation()
            if selected == "preview":
                return self._entry_owner._preview()
            if selected == "save":
                return self._entry_owner._save()
            if selected == "delete":
                return self._entry_owner._open_delete_confirmation()
            if selected == "dictionary":
                return self.open_menu(preserve_current=True)
            if selected == "back":
                return self._entry_owner._back_from_entry()
        if editor.kind == "dictionary_english_entry":
            if selected == "surface":
                return self._begin_field("surface", editor.payload["surface"])
            if selected == "phonemes":
                return self._begin_field(
                    "phonemes", " ".join(editor.payload["phonemes"])
                )
            if selected == "generate_pronunciation":
                return self._entry_owner._generate_pronunciation()
            if selected == "preview":
                return self._entry_owner._preview()
            if selected == "save":
                return self._entry_owner._save()
            if selected == "delete":
                return self._entry_owner._open_delete_confirmation()
            if selected == "dictionary":
                return self.open_menu(preserve_current=True)
            if selected == "back":
                return self._entry_owner._back_from_entry()
        if editor.kind == "dictionary_delete_confirmation":
            if selected == "delete":
                return self._entry_owner._delete_confirmed()
            if selected == "cancel":
                return self._entry_owner.restore_confirmation_parent(editor)
        if editor.kind == "dictionary_discard_confirmation":
            if selected == "discard":
                return self._entry_owner.confirm_discard(editor)
            if selected == "cancel":
                return self._entry_owner.restore_confirmation_parent(editor)
        return ()

    def _preview_list_word(
        self, *, allow_action: bool = False
    ) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None or editor.kind not in {
            "dictionary_japanese_list", "dictionary_english_list"
        }:
            return ()
        selected = editor.selection
        if isinstance(selected, tuple) and selected[0] == "entry":
            index = selected[1]
        elif allow_action and selected == "preview":
            index = editor.payload.get("entry_index")
        else:
            return ()
        entries = tuple(editor.payload.get("entries", ()))
        if not isinstance(index, int) or not 0 <= index < len(entries):
            return ()
        try:
            if editor.kind == "dictionary_japanese_list":
                _identity, word = entries[index]
                query = _japanese_preview_query(
                    _reading_morae(word.pronunciation), int(word.accent_type)
                )
            else:
                word = entries[index]
                query = _english_preview_query(word.surface, word.phonemes)
        except Exception as exc:
            editor.error = error_status(f"Preview failed: {exc}")
            return (UpdateStatusIntent(editor.error),)
        editor.error = EMPTY_STATUS
        return (PreviewIntent(query),)

    def _handle_list_prelude_key(
        self, key: Any,
    ) -> tuple[DictionaryControllerIntent, ...] | None:
        """Own list-specific pending-save gate, numbered jump, and preview keys.

        Return None to continue generic Dictionary key dispatch; an empty
        tuple means this list key was consumed without any new intents.
        """
        editor = self.editor
        if editor is None:
            return None
        if editor.kind == "dictionary_japanese_list":
            if self._deferred_list_key is not None:
                # Keep queued editor/delete/back navigation attached to its row.
                return ()
            if self._accent.has_pending and (
                (key in _ENTER_KEYS and editor.selection != "preview")
                or key in (_ESCAPE, "a", "x", "f", "q", "Q", "\x03")
                or (isinstance(key, str) and key in "1234567890")
            ):
                self._deferred_list_key = key
                self._accent.force_save()
                return (UpdateStatusIntent(info_status("Saving dictionary accents before continuing…")),)

        if editor.kind in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            was_number_jump = self._number_jump.active
            number_jump = self._number_jump.handle_key(
                key,
                item_count=len(editor.payload.get("entries", ())),
            )
            if number_jump.handled:
                self._sync_number_jump_payload(editor)
                if number_jump.warning is not None:
                    return (UpdateStatusIntent(warning_status(number_jump.warning)),)
                if number_jump.target_number is not None:
                    return self._open_list_entry_number(number_jump.target_number)
                return ()
            if key in (" ", "p", "P"):
                # During explicit number entry, no Preview shortcut fires.
                if was_number_jump or self._number_jump.active:
                    return ()
                return self._preview_list_word()

        return None

    def handle_key(
        self,
        key: Any,
        *,
        screen_width: int = 80,
        preview_busy: bool = False,
        dictionary_operation_busy: bool = False,
    ) -> tuple[DictionaryControllerIntent, ...]:
        editor = self.editor
        if editor is None:
            return ()
        list_accent_operation_busy = (
            editor.kind == "dictionary_japanese_list"
            and self._accent.inflight is not None
        )
        if dictionary_operation_busy and not list_accent_operation_busy:
            if key in ("q", "Q", "\x03"):
                return (QuitIntent(),)
            if key == "?":
                return (OpenHelpIntent(),)
            return ()
        if preview_busy and editor.kind in {
            "dictionary_japanese_entry",
            "dictionary_english_entry",
        }:
            return (
                UpdateStatusIntent(
                    "Wait for Preview to finish before editing the dictionary."
                ),
            )

        if editor.active_field is not None:
            if key in _ENTER_KEYS:
                return self._finish_field()
            if key == _ESCAPE:
                if editor.kind in {
                    "dictionary_japanese_filter",
                    "dictionary_english_filter",
                }:
                    self._restore_parent()
                    return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())
                if editor.kind == "dictionary_import_path":
                    self._import_owner._clear_import_state()
                    self._restore_parent()
                    return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())
                return self._entry_owner._back_from_entry()
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
                if edit.edit_attempted:
                    editor.error = EMPTY_STATUS
            return ()

        list_key = self._handle_list_prelude_key(key)
        if list_key is not None:
            return list_key

        if key in ("q", "Q", "\x03"):
            return (QuitIntent(),)
        if key == "?":
            return (OpenHelpIntent(),)

        if editor.kind in {
            "dictionary_japanese_entry",
            "dictionary_english_entry",
        }:
            direction: int | None = None
            show_adjustment_feedback = False
            if key == "[":
                direction = -1
            elif key == "]":
                direction = 1
            elif editor.selection == "entry_navigator":
                if key == curses.KEY_LEFT:
                    direction = -1
                    show_adjustment_feedback = True
                elif key == curses.KEY_RIGHT:
                    direction = 1
                    show_adjustment_feedback = True
            if direction is not None:
                return self._entry_owner._move_open_entry(
                    direction,
                    show_feedback=show_adjustment_feedback,
                )

        if editor.kind in {
            "dictionary_delete_confirmation",
            "dictionary_discard_confirmation",
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
                    return self._activate()
                return ()

        if (
            editor.kind == "dictionary_import_review"
            and key == " "
            and isinstance(editor.selection, tuple)
            and editor.selection[0] == "import_entry"
            and isinstance(editor.selection[1], int)
        ):
            index = editor.selection[1]
            items = tuple(editor.payload["items"])
            if 0 <= index < len(items):
                return self._import_owner._set_import_item_selected(
                    index,
                    not bool(items[index].selected),
                )

        if editor.kind in {
            "dictionary_japanese_entry",
            "dictionary_english_entry",
            "dictionary_japanese_filter",
            "dictionary_english_filter",
            "dictionary_menu",
            "dictionary_export",
            "dictionary_import_path",
            "dictionary_import_review",
            "dictionary_import_japanese_detail",
            "dictionary_import_english_detail",
        }:
            shortcut = resolve_shortcut(editor.kind, key, editor.payload)
            if shortcut is not None:
                editor.selection = shortcut.key
                editor.error = EMPTY_STATUS
                return self._activate()

        if editor.kind in {
            "dictionary_japanese_list",
            "dictionary_english_list",
        }:
            shortcut = resolve_shortcut(editor.kind, key, editor.payload)
            if shortcut is not None:
                if (
                    isinstance(editor.selection, tuple)
                    and editor.selection[0] == "entry"
                    and editor.selection[1] is not None
                ):
                    editor.payload["entry_index"] = editor.selection[1]
                    self._remember_list_focus(editor)
                editor.selection = shortcut.key
                editor.error = EMPTY_STATUS
                if shortcut.key == "sort":
                    return self._cycle_list_sort()
                return self._activate()
        if editor.kind == "dictionary_japanese_duplicates":
            shortcut = resolve_shortcut(editor.kind, key, editor.payload)
            if shortcut is not None and shortcut.key == "back":
                self.editor = None
                return (UpdateStatusIntent(""),)

        if key == _ESCAPE:
            if editor.kind in {
                "dictionary_japanese_entry",
                "dictionary_english_entry",
            }:
                return self._entry_owner._back_from_entry()
            if editor.kind in {
                "dictionary_import_japanese_detail",
                "dictionary_import_english_detail",
            }:
                return self._import_owner._back_from_import_detail()
            if editor.kind in {
                "dictionary_import_path",
                "dictionary_import_review",
            }:
                self._import_owner._clear_import_state()
            self._restore_parent()
            return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

        if key == curses.KEY_UP:
            if editor.kind in {
                "dictionary_japanese_entry",
                "dictionary_english_entry",
            }:
                return self._entry_owner._move_entry_selection(-1)
            return self._move_dynamic_selection(-1)
        if key == curses.KEY_DOWN:
            if editor.kind in {
                "dictionary_japanese_entry",
                "dictionary_english_entry",
            }:
                return self._entry_owner._move_entry_selection(1)
            return self._move_dynamic_selection(1)

        if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            direction = -1 if key == curses.KEY_LEFT else 1
            if editor.kind in {
                "dictionary_japanese_list",
                "dictionary_english_list",
            }:
                if editor.kind == "dictionary_japanese_list" and (
                    isinstance(editor.selection, tuple)
                    and editor.selection[0] == "entry"
                ):
                    changed = self._accent.move(editor, direction)
                    return adjustment_feedback_intents(
                        changed=changed,
                        area="dictionary",
                        control="list_accent",
                        direction=direction,
                    )
                if editor.selection == "sort":
                    return self._cycle_list_sort(
                        direction,
                        show_feedback=True,
                    )
                if editor.selection == "filter":
                    return self._set_list_filter_enabled(
                        not bool(editor.payload.get("filter_enabled")),
                        direction,
                    )
            if editor.kind == "dictionary_japanese_entry":
                return self._entry_owner._adjust_japanese(direction)
            if editor.kind == "dictionary_import_japanese_detail":
                return self._import_owner._adjust_import_word_type(direction)
            if editor.kind == "dictionary_english_entry":
                return self._entry_owner._adjust_english(direction)
            if editor.kind == "dictionary_japanese_filter":
                return self._adjust_filter(direction)

        if key in _ENTER_KEYS:
            return self._activate()
        return ()
