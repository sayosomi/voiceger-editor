"""Interaction state and policy for Dictionary Import."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Union

from .dictionary_import import (
    DictionaryImportFormat,
    DictionaryImportReview,
    prepare_dictionary_import,
)
from .tui_adjustments import step_cyclic
from .tui_dictionary_operations import (
    DictionaryLanguage,
    DictionaryOperationIntent,
    DictionaryOperationRequest,
    dictionary_operation_request,
)
from .tui_dictionary_word_types import (
    JAPANESE_WORD_TYPES as _WORD_TYPES,
    japanese_word_type_label as _japanese_word_type_label,
)
from .tui_editors import (
    ClearAdjustmentFeedbackIntent,
    EditorIntent,
    EditorState,
    UpdateStatusIntent,
    adjustment_feedback_intents,
)
from .tui_status import EMPTY_STATUS, error_status, info_status
from .user_dictionary import japanese_word_type


DictionaryImportIntent = Union[EditorIntent, DictionaryOperationIntent]


class DictionaryImportOwner:
    """Own Import review data, screens, and operation outcomes."""

    def __init__(
        self,
        core,
        *,
        get_editor: Callable[[], EditorState | None],
        set_editor: Callable[[EditorState | None], None],
        parent_stack: list[EditorState],
        output_dir: Callable[[], Path],
        menu_state: Callable[[], EditorState],
    ) -> None:
        self.core = core
        self._get_editor = get_editor
        self._set_editor = set_editor
        self._stack = parent_stack
        self._output_dir = output_dir
        self._menu_state = menu_state
        self._import_review: DictionaryImportReview | None = None
        self._import_source_path = ""

    @property
    def editor(self) -> EditorState | None:
        return self._get_editor()

    @editor.setter
    def editor(self, value: EditorState | None) -> None:
        self._set_editor(value)

    def _clear_import_state(self) -> None:
        self._import_review = None
        self._import_source_path = ""

    def _default_input_path(self) -> str:
        path = str(Path(self._output_dir()))
        return path if path.endswith(os.sep) else path + os.sep

    def _import_path_state(self, path: str | None = None) -> EditorState:
        return EditorState(
            kind="dictionary_import_path",
            title="IMPORT DICTIONARY",
            origin=("dictionary", None),
            selection="path",
            payload={
                "path": self._default_input_path() if path is None else path,
            },
        )

    @staticmethod
    def _import_item_identity(item: Any) -> tuple[str, str]:
        source_uuid = getattr(item, "source_uuid", None)
        if source_uuid is not None:
            return ("ja", str(source_uuid))
        incoming = item.incoming
        return ("en", str(incoming.surface).strip().casefold())

    def _import_review_state(
        self,
        *,
        preferred_identity: tuple[str, str] | None = None,
        preferred_index: int | None = None,
        action: str | None = None,
    ) -> EditorState:
        review = self._import_review
        if review is None:
            raise RuntimeError("dictionary import review is not available")
        items = tuple(review.items)
        word_type_labels = (
            tuple(
                _japanese_word_type_label(japanese_word_type(item.incoming))
                for item in items
            )
            if review.format is DictionaryImportFormat.JAPANESE
            else ()
        )
        selection: str | tuple[str, int | None]
        if action is not None:
            selection = action
        elif items:
            index = 0
            if preferred_identity is not None:
                for candidate_index, item in enumerate(items):
                    if self._import_item_identity(item) == preferred_identity:
                        index = candidate_index
                        break
                else:
                    if preferred_index is not None:
                        index = min(max(preferred_index, 0), len(items) - 1)
            elif preferred_index is not None:
                index = min(max(preferred_index, 0), len(items) - 1)
            selection = ("import_entry", index)
        else:
            selection = "import_selected"
        return EditorState(
            kind="dictionary_import_review",
            title="IMPORT DICTIONARY",
            origin=("dictionary", None),
            selection=selection,
            payload={
                "format": review.format.value,
                "source_path": self._import_source_path,
                "items": items,
                "word_type_labels": word_type_labels,
                "total_count": review.total_count,
                "exact_duplicate_count": review.exact_duplicate_count,
                "review_count": len(items),
            },
        )

    def _import_detail_state(self, index: int) -> EditorState:
        review = self._import_review
        if review is None:
            raise RuntimeError("dictionary import review is not available")
        items = tuple(review.items)
        if not 0 <= index < len(items):
            raise IndexError("dictionary import review entry is out of range")
        item = items[index]
        identity = self._import_item_identity(item)
        if review.format is DictionaryImportFormat.JAPANESE:
            word_type = japanese_word_type(item.incoming)
            existing_word_type = (
                None if item.existing is None else japanese_word_type(item.existing)
            )
            return EditorState(
                kind="dictionary_import_japanese_detail",
                title="IMPORT JAPANESE WORD",
                origin=("dictionary", None),
                selection="word_type",
                payload={
                    "identity": identity,
                    "item_index": index,
                    "item": item,
                    "word_type": word_type,
                    "word_type_label": _japanese_word_type_label(word_type),
                    "existing_word_type": existing_word_type,
                    "existing_word_type_label": (
                        None
                        if existing_word_type is None
                        else _japanese_word_type_label(existing_word_type)
                    ),
                },
            )
        return EditorState(
            kind="dictionary_import_english_detail",
            title="IMPORT ENGLISH WORD",
            origin=("dictionary", None),
            selection="back",
            payload={
                "identity": identity,
                "item_index": index,
                "item": item,
            },
        )

    def _load_dictionary_import(self) -> tuple[DictionaryImportIntent, ...]:
        editor = self.editor
        assert editor is not None
        path = str(editor.payload.get("path", "")).strip()
        if not path:
            editor.error = error_status("Dictionary import path must not be empty.")
            return ()
        editor.error = EMPTY_STATUS
        core = self.core

        def work() -> DictionaryImportReview:
            return prepare_dictionary_import(path, core)

        request = dictionary_operation_request(
            editor,
            operation="load_dictionary_import",
            language=None,
        )
        return (
            DictionaryOperationIntent(
                request,
                info_status("Loading dictionary import…"),
                work,
            ),
        )

    def _commit_dictionary_import(self) -> tuple[DictionaryImportIntent, ...]:
        editor = self.editor
        review = self._import_review
        if editor is None or review is None:
            return ()
        language: DictionaryLanguage = (
            "ja" if review.format is DictionaryImportFormat.JAPANESE else "en"
        )
        core = self.core

        def work() -> Any:
            return review.commit(core)

        request = dictionary_operation_request(
            editor,
            operation="commit_dictionary_import",
            language=language,
        )
        return (
            DictionaryOperationIntent(
                request,
                info_status("Importing selected dictionary words…"),
                work,
            ),
        )

    def _set_import_item_selected(
        self,
        index: int,
        selected: bool,
    ) -> tuple[EditorIntent, ...]:
        review = self._import_review
        if review is None:
            return ()
        items = tuple(review.items)
        if not 0 <= index < len(items):
            return ()
        item = items[index]
        identity = self._import_item_identity(item)
        if review.format is DictionaryImportFormat.JAPANESE:
            review.set_selected(item.source_uuid, selected)
        else:
            review.set_selected(item.incoming.surface, selected)
        self.editor = self._import_review_state(preferred_identity=identity)
        return ()

    def _clear_import_selection(self) -> tuple[EditorIntent, ...]:
        review = self._import_review
        if review is None:
            return ()
        for item in tuple(review.items):
            if review.format is DictionaryImportFormat.JAPANESE:
                review.set_selected(item.source_uuid, False)
            else:
                review.set_selected(item.incoming.surface, False)
        self.editor = self._import_review_state(action="clear_selection")
        return (UpdateStatusIntent("Dictionary import selection cleared."),)

    def _back_from_import_detail(self) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        self.editor = self._import_review_state(
            preferred_identity=editor.payload.get("identity"),
            preferred_index=editor.payload.get("item_index"),
        )
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _adjust_import_word_type(self, direction: int) -> tuple[EditorIntent, ...]:
        editor = self.editor
        review = self._import_review
        if (
            editor is None
            or editor.kind != "dictionary_import_japanese_detail"
            or review is None
            or review.format is not DictionaryImportFormat.JAPANESE
            or editor.selection != "word_type"
        ):
            return ()
        identity = editor.payload.get("identity")
        index = int(editor.payload.get("item_index", 0))
        items = tuple(review.items)
        item = next(
            (
                candidate
                for candidate in items
                if self._import_item_identity(candidate) == identity
            ),
            None,
        )
        if item is None:
            self.editor = self._import_review_state(preferred_index=index)
            return (UpdateStatusIntent("This entry no longer requires review."),)
        current = japanese_word_type(item.incoming)
        result = step_cyclic(current, _WORD_TYPES, direction=direction)
        if not result.changed:
            return adjustment_feedback_intents(
                changed=False,
                area="dictionary",
                control="word_type",
                direction=direction,
            )
        try:
            review.set_word_type(item.source_uuid, result.value)
        except Exception as exc:
            editor.error = error_status(f"Word type was not changed: {exc}")
            return ()
        updated_items = tuple(review.items)
        for updated_index, candidate in enumerate(updated_items):
            if self._import_item_identity(candidate) == identity:
                self.editor = self._import_detail_state(updated_index)
                return adjustment_feedback_intents(
                    changed=True,
                    area="dictionary",
                    control="word_type",
                    direction=direction,
                )
        self.editor = self._import_review_state(preferred_index=index)
        return (
            UpdateStatusIntent(
                "Entry now exactly matches the dictionary and no longer requires review."
            ),
            ClearAdjustmentFeedbackIntent(),
        )

    def complete_operation(
        self,
        request: DictionaryOperationRequest,
        value: Any = None,
        error: BaseException | None = None,
    ) -> tuple[EditorIntent, ...]:
        editor = self.editor
        assert editor is not None
        if error is not None:
            message = (
                f"Dictionary import was not loaded: {error}"
                if request.operation == "load_dictionary_import"
                else f"Dictionary import was not completed: {error}"
            )
            editor.error = error_status(message)
            return (UpdateStatusIntent(editor.error),)

        editor.error = EMPTY_STATUS
        if request.operation == "load_dictionary_import":
            self._import_review = value
            self._import_source_path = str(
                request.editor_snapshot.payload.get("path", "")
            )
            self.editor = self._import_review_state()
            return (
                UpdateStatusIntent(
                    f"Dictionary import ready: {value.total_count} words found."
                ),
                ClearAdjustmentFeedbackIntent(),
            )

        result = value
        if self._stack and self._stack[-1].kind == "dictionary_menu":
            self._stack.pop()
        self._clear_import_state()
        self.editor = self._menu_state()
        return (
            UpdateStatusIntent(
                "Dictionary import complete: "
                f"{result.imported} imported, "
                f"{result.replaced} replaced, "
                f"{result.skipped} skipped."
            ),
            ClearAdjustmentFeedbackIntent(),
        )
