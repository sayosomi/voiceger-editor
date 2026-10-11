"""Japanese Dictionary word-list inline accent position editing."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .tui_dictionary_entry import _reading_morae
from .tui_dictionary_inline_edits import DictionaryListAutoSaveOwner
from .tui_editors import EditorState


class JapaneseListAccentOwner(DictionaryListAutoSaveOwner):
    """Japanese mora-bounded edits backed by the shared deferred-save lifecycle."""

    editor_kind = "dictionary_japanese_list"
    operation = "save_japanese_list_accents"
    language = "ja"
    pending_flag = "accent_pending"
    saving_flag = "accent_saving"
    saving_message = "Saving Japanese dictionary accents…"

    def persist(self, snapshot: Mapping[str, Any]) -> None:
        self.core.update_japanese_accents(snapshot)

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
        self.mark_changed(editor, identity, target)
        return True
