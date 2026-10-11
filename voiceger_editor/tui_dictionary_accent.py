"""Debounced, single-worker Japanese Dictionary list accent editing."""

from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import Any, Sequence

from .tui_dictionary_entry import _reading_morae
from .tui_dictionary_operations import (
    DictionaryOperationIntent,
    dictionary_operation_request,
)
from .tui_editors import EditorState
from .tui_status import info_status


class JapaneseListAccentOwner:
    """Keep optimistic word accents separate from persisted dictionary records.

    Only the UI thread touches this owner. Worker closures receive fixed
    snapshots; completion is reconciled against newer visible changes.
    """

    DEBOUNCE_SECONDS = 0.35

    def __init__(self, core: Any) -> None:
        self.core = core
        self.pending: dict[str, int] = {}
        self.inflight: dict[str, int] | None = None
        self.next_save_at = 0.0

    @property
    def has_pending(self) -> bool:
        return bool(self.pending) or self.inflight is not None

    def force_save(self) -> None:
        self.next_save_at = 0.0

    def overlay(
        self, entries: Sequence[tuple[str, Any]]
    ) -> tuple[tuple[str, Any], ...]:
        visible = []
        for identity, word in entries:
            if identity in self.pending and word.accent_type != self.pending[identity]:
                word = deepcopy(word)
                word.accent_type = self.pending[identity]
            visible.append((identity, word))
        return tuple(visible)

    def move(self, editor: EditorState, direction: int) -> bool:
        selection = editor.selection
        if not (
            isinstance(selection, tuple)
            and len(selection) == 2
            and selection[0] == "entry"
            and isinstance(selection[1], int)
        ):
            return False
        index = selection[1]
        entries = list(editor.payload["entries"])
        if not 0 <= index < len(entries):
            return False
        identity, word = entries[index]
        mora_count = len(_reading_morae(word.pronunciation))
        if not mora_count:
            return False
        current_visual = word.accent_type or mora_count
        target = min(mora_count, max(1, current_visual + (-1 if direction < 0 else 1)))
        if target == current_visual:
            return False
        updated = deepcopy(word)
        updated.accent_type = target
        entries[index] = (identity, updated)
        editor.payload["entries"] = tuple(entries)
        self.pending[identity] = target
        self.next_save_at = monotonic() + self.DEBOUNCE_SECONDS
        editor.payload["accent_pending"] = True
        return True

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
            or editor.kind != "dictionary_japanese_list"
            or (monotonic() if now is None else now) < self.next_save_at
        ):
            return None
        snapshot = dict(self.pending)
        self.inflight = snapshot
        editor.payload["accent_saving"] = True
        request = dictionary_operation_request(
            editor, operation="save_japanese_list_accents", language="ja"
        )
        core = self.core

        def work() -> None:
            core.update_japanese_accents(snapshot)

        return DictionaryOperationIntent(
            request,
            info_status("Saving Japanese dictionary accents…"),
            work,
        )

    def complete(self, error: BaseException | None) -> None:
        snapshot = self.inflight
        if snapshot is None:
            raise RuntimeError("No Japanese list accent save is active")
        self.inflight = None
        if error is not None:
            # The core restores its on-disk and OpenJTalk state on failure.
            # Discard optimistic values explicitly and report the failure.
            self.pending.clear()
            return
        for identity, accent in snapshot.items():
            if self.pending.get(identity) == accent:
                del self.pending[identity]
        if self.pending:
            self.next_save_at = monotonic() + self.DEBOUNCE_SECONDS
