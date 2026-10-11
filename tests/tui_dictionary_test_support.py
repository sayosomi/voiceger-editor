"""Shared fixtures for focused Dictionary TUI regression tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from voiceger_editor.openjtalk_dictionary import expand_word_type, normalize_surface
from voiceger_editor.tui_dictionary import (
    DictionaryOperationIntent,
    TuiDictionaryController,
)
from voiceger_editor.user_dictionary import JapaneseWordType, UserDictWord


def ja_word(
    surface,
    pronunciation="ズンダモン",
    accent=3,
    *,
    priority=5,
    word_type=JapaneseWordType.PROPER_NOUN,
):
    expanded = expand_word_type(word_type.value)
    return SimpleNamespace(
        surface=normalize_surface(surface),
        pronunciation=pronunciation,
        accent_type=accent,
        priority=priority,
        context_id=expanded["context_id"],
    )


def en_word(surface, phonemes):
    return SimpleNamespace(surface=surface, phonemes=list(phonemes))


def import_ja_word(
    surface,
    pronunciation="ズンダモン",
    accent=3,
    *,
    priority=5,
    word_type=JapaneseWordType.PROPER_NOUN,
):
    return UserDictWord.model_validate(
        {
            "surface": surface,
            "priority": priority,
            **expand_word_type(word_type.value),
            "inflectional_type": "*",
            "inflectional_form": "*",
            "stem": "*",
            "yomi": pronunciation,
            "pronunciation": pronunciation,
            "accent_type": accent,
            "mora_count": None,
            "accent_associative_rule": "*",
        }
    )


class FakeDictionaryCore:
    def __init__(self):
        self.japanese = {}
        self.english = {}
        self.next_id = 1

    def list_japanese_entries(self):
        return dict(self.japanese)

    def list_english_entries(self):
        return dict(self.english)

    def add_japanese_word(self, **values):
        word_uuid = f"word-{self.next_id}"
        self.next_id += 1
        self.japanese[word_uuid] = ja_word(
            values["surface"],
            values["pronunciation"],
            values["accent_type"],
            priority=values["priority"],
            word_type=values["word_type"],
        )
        return word_uuid

    def update_japanese_word(self, word_uuid, **values):
        self.japanese[word_uuid] = ja_word(
            values["surface"],
            values["pronunciation"],
            values["accent_type"],
            priority=values["priority"],
            word_type=values["word_type"],
        )

    def update_japanese_accents(self, accents):
        from copy import deepcopy
        for word_uuid, accent in accents.items():
            word = deepcopy(self.japanese[word_uuid])
            word.accent_type = accent
            self.japanese[word_uuid] = word

    def delete_japanese_word(self, word_uuid):
        del self.japanese[word_uuid]

    def set_english_entry(self, surface, phonemes):
        key = surface.strip().casefold()
        self.english = {
            old_surface: entry
            for old_surface, entry in self.english.items()
            if old_surface.strip().casefold() != key
        }
        entry = en_word(surface, phonemes)
        self.english[surface] = entry
        return entry

    def update_english_entry(self, original_surface, *, surface, phonemes):
        original_key = original_surface.strip().casefold()
        if not any(
            old_surface.strip().casefold() == original_key
            for old_surface in self.english
        ):
            raise ValueError("not found")
        for old_surface in tuple(self.english):
            if old_surface.strip().casefold() == original_key:
                del self.english[old_surface]
        entry = en_word(surface, phonemes)
        self.english[surface] = entry
        return entry

    def delete_english_entry(self, surface):
        key = surface.strip().casefold()
        for old_surface in tuple(self.english):
            if old_surface.strip().casefold() == key:
                del self.english[old_surface]
                return
        raise ValueError("not found")

    def import_english(self, entries, *, override=False):
        for surface, phonemes in entries.items():
            self.set_english_entry(surface, phonemes)

    def import_japanese(self, entries, *, override=False):
        self.japanese.update(entries)


class DictionaryControllerTestCase(unittest.TestCase):
    def setUp(self):
        self.core = FakeDictionaryCore()
        self.controller = TuiDictionaryController(
            self.core,
            input_prefix=lambda _editor: "▶ ",
        )

    def key(self, value):
        return self.controller.handle_key(value)

    def finish_operation(self, intents):
        operation = next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )
        value = operation.work()
        completion = self.controller.complete_operation(operation.request, value)
        return operation, completion

    @staticmethod
    def operation(intents):
        return next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )
