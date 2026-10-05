import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from voiceger_editor.tui_dictionary import (
    DictionaryOperationIntent,
    TuiDictionaryController,
)
from voiceger_editor.user_dictionary import (
    JapaneseDictionaryEntryRelation,
    JapaneseWordType,
    UserDictWord,
    UserDictionaryCore,
    UserDictionaryInputError,
)


class FakeBackend:
    def __init__(self):
        self.active = {}

    def ensure_active(self, entries, *, force=False):
        if force:
            self.active = dict(entries)

    def activate_entries(self, entries):
        previous = dict(self.active)
        self.active = dict(entries)
        return previous

    def commit(self, _previous):
        return None


class JapaneseDictionaryIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.voiceger_root = self.root / "voiceger"
        self.voiceger_root.mkdir()
        self.data_dir = self.root / "adapter-state"
        self.core = UserDictionaryCore(
            self.voiceger_root,
            data_directory=self.data_dir,
            openjtalk_dictionary=FakeBackend(),
        )

    def tearDown(self):
        self.temp.cleanup()

    def add_word(self, **kwargs):
        values = {
            "surface": "ずんだもん",
            "pronunciation": "ズンダモン",
            "accent_type": 3,
        }
        values.update(kwargs)
        return self.core.add_japanese_word(**values)

    def test_add_uses_normalized_surface_and_word_type_identity(self):
        first_uuid = self.add_word(
            surface="ABC!",
            word_type=JapaneseWordType.PROPER_NOUN,
        )

        with self.assertRaisesRegex(
            UserDictionaryInputError,
            "同じSurfaceと品詞",
        ):
            self.add_word(
                surface="ＡＢＣ！",
                word_type=JapaneseWordType.PROPER_NOUN,
            )

        second_uuid = self.add_word(
            surface="ＡＢＣ！",
            word_type=JapaneseWordType.COMMON_NOUN,
        )
        entries = self.core.list_japanese_entries()

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[first_uuid].surface, "ＡＢＣ！")
        self.assertEqual(entries[second_uuid].surface, "ＡＢＣ！")
        self.assertNotEqual(
            entries[first_uuid].context_id,
            entries[second_uuid].context_id,
        )

    def test_edit_rejects_identity_collision_without_changing_uuid_entries(self):
        first_uuid = self.add_word(
            surface="雨",
            word_type=JapaneseWordType.PROPER_NOUN,
        )
        second_uuid = self.add_word(
            surface="飴",
            word_type=JapaneseWordType.PROPER_NOUN,
        )
        before = self.core.list_japanese_entries()

        with self.assertRaisesRegex(
            UserDictionaryInputError,
            "同じSurfaceと品詞",
        ):
            self.core.update_japanese_word(
                second_uuid,
                surface="雨",
                pronunciation="ズンダモン",
                accent_type=3,
                word_type=JapaneseWordType.PROPER_NOUN,
            )

        self.assertEqual(self.core.list_japanese_entries(), before)
        self.assertIn(first_uuid, before)
        self.assertIn(second_uuid, before)

    def test_classification_distinguishes_exact_conflict_and_new(self):
        word_uuid = self.add_word(
            surface="ABC!",
            word_type=JapaneseWordType.PROPER_NOUN,
        )
        stored = self.core.list_japanese_entries()[word_uuid]
        exact = UserDictWord.model_validate(
            {**stored.model_dump(), "surface": "ABC!"}
        )
        conflict = UserDictWord.model_validate(
            {**stored.model_dump(), "priority": 6}
        )
        new_entry = UserDictWord.model_validate(
            {**stored.model_dump(), "surface": "別語"}
        )

        exact_result = self.core.classify_japanese_word(exact)
        conflict_result = self.core.classify_japanese_word(conflict)
        new_result = self.core.classify_japanese_word(new_entry)

        self.assertIs(
            exact_result.relation,
            JapaneseDictionaryEntryRelation.EXACT,
        )
        self.assertEqual(exact_result.existing_uuid, word_uuid)
        self.assertIs(
            conflict_result.relation,
            JapaneseDictionaryEntryRelation.CONFLICT,
        )
        self.assertEqual(conflict_result.existing_uuid, word_uuid)
        self.assertIs(
            new_result.relation,
            JapaneseDictionaryEntryRelation.NEW,
        )
        self.assertIsNone(new_result.existing_uuid)

    def test_quick_save_updates_existing_logical_entry_without_new_uuid(self):
        word_uuid = self.core.add_japanese_word(
            surface="雨",
            pronunciation="アメ",
            accent_type=0,
            word_type=JapaneseWordType.PROPER_NOUN,
        )
        controller = TuiDictionaryController(
            self.core,
            input_prefix=lambda _editor: "▶ ",
        )
        controller.open_quick_save_japanese(
            surface="雨",
            pronunciation="ア'メ",
        )

        self.assertEqual(controller.editor.payload["word_uuid"], word_uuid)
        intents = controller.handle_key("s")
        operation = next(
            intent for intent in intents
            if isinstance(intent, DictionaryOperationIntent)
        )
        value = operation.work()
        controller.complete_operation(operation.request, value=value)

        entries = self.core.list_japanese_entries()
        self.assertEqual(list(entries), [word_uuid])
        self.assertEqual(entries[word_uuid].accent_type, 1)


if __name__ == "__main__":
    unittest.main()
