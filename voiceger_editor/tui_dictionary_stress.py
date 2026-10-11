"""English Dictionary word-list inline primary-stress adjustment."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .english_stress import (
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
)
from .tui_dictionary_inline_edits import DictionaryListAutoSaveOwner
from .tui_editors import EditorState


class EnglishListStressOwner(DictionaryListAutoSaveOwner):
    """Move one unique ARPAbet primary marker by vowel, as in BATCH ITEM."""

    editor_kind = "dictionary_english_list"
    operation = "save_english_list_stresses"
    language = "en"
    pending_flag = "stress_pending"
    saving_flag = "stress_saving"
    saving_message = "Saving English dictionary stresses…"

    def persist(self, snapshot: Mapping[str, Any]) -> None:
        self.core.update_english_stresses(snapshot)

    def overlay(self, entries: Sequence[Any]) -> tuple[Any, ...]:
        visible = []
        for word in entries:
            pending = self.pending.get(word.surface)
            if pending is not None and tuple(word.phonemes) != pending:
                word = deepcopy(word)
                word.phonemes = list(pending)
            visible.append(word)
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

        word = entries[index]
        state = english_phonemes_to_editor_state(word.phonemes)
        primary = state.primary_stress_vowel_positions
        if direction not in (-1, 1) or len(primary) != 1:
            return False
        source = primary[0]
        target = source + direction
        if not 0 <= target < len(state.vowel_stresses):
            return False

        moved = move_primary_stress(state, source, target)
        tokens = tuple(editor_state_to_english_phonemes(moved))
        updated = deepcopy(word)
        updated.phonemes = list(tokens)
        entries[index] = updated
        editor.payload["entries"] = tuple(entries)
        identities = tuple(editor.payload["entry_ids"])
        self.mark_changed(editor, identities[index], tokens)
        return True
