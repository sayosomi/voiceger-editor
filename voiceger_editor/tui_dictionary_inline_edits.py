"""Shared debounce and deferred-save lifecycle for Dictionary word-list edits."""

from __future__ import annotations

from time import monotonic
from typing import Any, Mapping

from .tui_dictionary_operations import DictionaryOperationIntent, dictionary_operation_request
from .tui_editors import EditorState
from .tui_status import info_status


class DictionaryListAutoSaveOwner:
    """UI-thread optimistic changes with one immutable in-flight worker snapshot.

    Language owners provide word transformations and atomic persistence.
    Both languages use the existing single deferred Dictionary worker.
    """

    DEBOUNCE_SECONDS = 0.35
    editor_kind = ""
    operation = ""
    language = ""
    pending_flag = ""
    saving_flag = ""
    saving_message = ""

    def __init__(self, core: Any) -> None:
        self.core = core
        self.pending: dict[str, Any] = {}
        self.inflight: dict[str, Any] | None = None
        self.next_save_at = 0.0

    @property
    def has_pending(self) -> bool:
        return bool(self.pending) or self.inflight is not None

    def force_save(self) -> None:
        self.next_save_at = 0.0

    def mark_changed(self, editor: EditorState, identity: str, value: Any) -> None:
        self.pending[identity] = value
        self.next_save_at = monotonic() + self.DEBOUNCE_SECONDS
        editor.payload[self.pending_flag] = True

    def persist(self, snapshot: Mapping[str, Any]) -> None:
        raise NotImplementedError

    def begin(
        self,
        editor: EditorState,
        *,
        operation_busy: bool,
        now: float | None = None,
    ) -> DictionaryOperationIntent | None:
        if (
            operation_busy
            or self.inflight is not None
            or not self.pending
            or editor.kind != self.editor_kind
            or (monotonic() if now is None else now) < self.next_save_at
        ):
            return None
        snapshot = dict(self.pending)
        self.inflight = snapshot
        editor.payload[self.saving_flag] = True
        request = dictionary_operation_request(
            editor, operation=self.operation, language=self.language
        )

        def work() -> None:
            self.persist(snapshot)

        return DictionaryOperationIntent(
            request, info_status(self.saving_message), work
        )

    def complete(self, error: BaseException | None) -> None:
        snapshot = self.inflight
        if snapshot is None:
            raise RuntimeError("No Dictionary list edit save is active")
        self.inflight = None
        if error is not None:
            self.pending.clear()
            return
        for identity, value in snapshot.items():
            if self.pending.get(identity) == value:
                del self.pending[identity]
        if self.pending:
            self.next_save_at = monotonic() + self.DEBOUNCE_SECONDS
