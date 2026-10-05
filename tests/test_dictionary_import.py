import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from voiceger_editor.dictionary_import import (
    DictionaryImportError,
    DictionaryImportFormat,
    DictionaryImportRelation,
    EnglishDictionaryImportReview,
    JapaneseDictionaryImportReview,
    load_dictionary_import,
    prepare_dictionary_import,
)
from voiceger_editor.openjtalk_dictionary import expand_word_type
from voiceger_editor.user_dictionary import (
    JapaneseWordType,
    UserDictWord,
    UserDictionaryCore,
)


class _BackendState:
    def __init__(self, entries):
        self.entries = dict(entries)
        self.compilation = None


class FakeBackend:
    def __init__(self):
        self.active = {}

    def ensure_active(self, entries, *, force=False):
        if force:
            self.active = dict(entries)

    def snapshot(self):
        return _BackendState(self.active)

    def activate_entries(self, entries):
        previous = self.snapshot()
        self.active = dict(entries)
        return previous

    def restore(self, state):
        self.active = dict(state.entries)

    def commit(self, _previous):
        return None


def make_word(
    surface,
    pronunciation,
    accent_type,
    *,
    word_type=JapaneseWordType.PROPER_NOUN,
    priority=5,
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
            "accent_type": accent_type,
            "mora_count": None,
            "accent_associative_rule": "*",
        }
    )


class DictionaryImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.voiceger_root = self.root / "voiceger"
        self.voiceger_root.mkdir()
        self.data_dir = self.root / "adapter-state"
        self.backend = FakeBackend()
        self.core = UserDictionaryCore(
            self.voiceger_root,
            data_directory=self.data_dir,
            openjtalk_dictionary=self.backend,
        )

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, name, payload):
        path = self.root / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_content_based_detection_accepts_japanese_and_english_native_shapes(self):
        japanese_uuid = "11111111-1111-4111-8111-111111111111"
        japanese_word = make_word("雨", "アメ", 0)
        japanese_path = self.write_json(
            "english_user_dict.json",
            {japanese_uuid: japanese_word.model_dump(mode="json")},
        )
        english_path = self.write_json(
            "user_dict.json",
            {"Voiceger": ["V", "OY1", "AH0", "JH", "ER0"]},
        )

        japanese = load_dictionary_import(japanese_path)
        english = load_dictionary_import(english_path)

        self.assertIs(japanese.format, DictionaryImportFormat.JAPANESE)
        self.assertEqual(japanese.japanese_entries[0][0], japanese_uuid)
        self.assertIs(english.format, DictionaryImportFormat.ENGLISH)
        self.assertEqual(english.english_entries[0].surface, "Voiceger")

    def test_path_expands_home(self):
        path = self.write_json(
            "words.json",
            {"Voiceger": ["V", "OY1", "AH0", "JH", "ER0"]},
        )
        with patch.dict(os.environ, {"HOME": str(self.root)}):
            parsed = load_dictionary_import("~/words.json")
        self.assertEqual(parsed.source_path, path)

    def test_rejects_malformed_unsupported_invalid_uuid_and_invalid_word(self):
        malformed = self.root / "malformed.json"
        malformed.write_text("{", encoding="utf-8")
        unsupported = self.write_json("unsupported.json", {"word": "not-an-array"})
        invalid_uuid = self.write_json(
            "invalid-uuid.json",
            {"not-a-uuid": make_word("雨", "アメ", 0).model_dump(mode="json")},
        )
        invalid_word_payload = make_word("雨", "アメ", 0).model_dump(mode="json")
        invalid_word_payload["priority"] = 99
        invalid_word = self.write_json(
            "invalid-word.json",
            {"11111111-1111-4111-8111-111111111111": invalid_word_payload},
        )

        for path in (malformed, unsupported, invalid_uuid, invalid_word):
            with self.subTest(path=path.name):
                with self.assertRaises(DictionaryImportError):
                    load_dictionary_import(path)

    def test_whole_file_validation_happens_before_dictionary_mutation(self):
        existing_uuid = self.core.add_japanese_word(
            surface="既存",
            pronunciation="キソン",
            accent_type=0,
        )
        before_entries = self.core.list_japanese_entries()
        before_file = self.core.japanese_path.read_bytes()
        valid = make_word("新語", "シンゴ", 0).model_dump(mode="json")
        invalid = make_word("壊れ", "コワレ", 0).model_dump(mode="json")
        invalid["accent_type"] = 99
        path = self.write_json(
            "mixed-validity.json",
            {
                "11111111-1111-4111-8111-111111111111": valid,
                "22222222-2222-4222-8222-222222222222": invalid,
            },
        )

        with self.assertRaises(DictionaryImportError):
            prepare_dictionary_import(path, self.core)

        self.assertEqual(self.core.list_japanese_entries(), before_entries)
        self.assertEqual(self.core.japanese_path.read_bytes(), before_file)
        self.assertIn(existing_uuid, before_entries)

    def test_japanese_review_classifies_and_commit_preserves_uuid_and_order(self):
        exact_uuid = self.core.add_japanese_word(
            surface="同一",
            pronunciation="ドウイツ",
            accent_type=0,
        )
        conflict_uuid = self.core.add_japanese_word(
            surface="衝突",
            pronunciation="ショウトツ",
            accent_type=0,
        )
        base = self.core.list_japanese_entries()
        exact_word = base[exact_uuid]
        conflict_word = UserDictWord.model_validate(
            {
                **base[conflict_uuid].model_dump(mode="python"),
                "priority": 6,
            }
        )
        new_uuid = "33333333-3333-4333-8333-333333333333"
        new_word = make_word("新語", "シンゴ", 0)
        path = self.write_json(
            "japanese.json",
            {
                "11111111-1111-4111-8111-111111111111":
                    exact_word.model_dump(mode="json"),
                "22222222-2222-4222-8222-222222222222":
                    conflict_word.model_dump(mode="json"),
                new_uuid: new_word.model_dump(mode="json"),
            },
        )

        review = prepare_dictionary_import(path, self.core)
        self.assertIsInstance(review, JapaneseDictionaryImportReview)
        self.assertEqual(review.exact_duplicate_count, 1)
        self.assertEqual(len(review.items), 2)
        by_surface = {item.incoming.surface: item for item in review.items}
        self.assertIs(
            by_surface["衝突"].relation,
            DictionaryImportRelation.CONFLICT,
        )
        self.assertFalse(by_surface["衝突"].selected)
        self.assertEqual(by_surface["衝突"].existing_uuid, conflict_uuid)
        self.assertIs(by_surface["新語"].relation, DictionaryImportRelation.NEW)
        self.assertTrue(by_surface["新語"].selected)

        review.set_selected(by_surface["衝突"].source_uuid, True)
        result = review.commit(self.core)

        self.assertEqual((result.imported, result.replaced, result.skipped), (1, 1, 1))
        entries = self.core.list_japanese_entries()
        self.assertEqual(
            list(entries),
            [exact_uuid, conflict_uuid, new_uuid],
        )
        self.assertEqual(entries[conflict_uuid].priority, 6)
        self.assertEqual(entries[new_uuid].surface, "新語")

    def test_japanese_word_type_edit_recomputes_new_conflict_and_exact(self):
        self.core.add_japanese_word(
            surface="雨",
            pronunciation="アメ",
            accent_type=0,
            word_type=JapaneseWordType.PROPER_NOUN,
            priority=5,
        )
        self.core.add_japanese_word(
            surface="雨",
            pronunciation="アメ",
            accent_type=0,
            word_type=JapaneseWordType.SUFFIX,
            priority=6,
        )
        source_uuid = "44444444-4444-4444-8444-444444444444"
        incoming = make_word(
            "雨",
            "アメ",
            0,
            word_type=JapaneseWordType.COMMON_NOUN,
            priority=6,
        )
        path = self.write_json(
            "word-type.json",
            {source_uuid: incoming.model_dump(mode="json")},
        )
        review = prepare_dictionary_import(path, self.core)

        self.assertIs(review.items[0].relation, DictionaryImportRelation.NEW)
        review.set_word_type(source_uuid, JapaneseWordType.PROPER_NOUN)
        self.assertIs(review.items[0].relation, DictionaryImportRelation.CONFLICT)
        self.assertFalse(review.items[0].selected)
        review.set_word_type(source_uuid, JapaneseWordType.SUFFIX)
        self.assertEqual(review.items, ())
        self.assertEqual(review.exact_duplicate_count, 1)

    def test_japanese_review_exposes_copies_so_only_review_methods_mutate_state(self):
        source_uuid = "55555555-5555-4555-8555-555555555555"
        incoming = make_word("保護", "ホゴ", 0, priority=6)
        path = self.write_json(
            "readonly.json",
            {source_uuid: incoming.model_dump(mode="json")},
        )
        review = prepare_dictionary_import(path, self.core)

        item = review.items[0]
        item.incoming.priority = 1
        result = review.commit(self.core)

        self.assertEqual(result.imported, 1)
        self.assertEqual(self.core.list_japanese_entries()[source_uuid].priority, 6)

    def test_japanese_commit_rolls_back_persistence_and_runtime_on_failure(self):
        existing_uuid = self.core.add_japanese_word(
            surface="既存",
            pronunciation="キソン",
            accent_type=0,
        )
        before_entries = self.core.list_japanese_entries()
        before_file = self.core.japanese_path.read_bytes()
        before_active = dict(self.backend.active)
        new_uuid = "66666666-6666-4666-8666-666666666666"
        path = self.write_json(
            "atomic-japanese.json",
            {new_uuid: make_word("追加", "ツイカ", 0).model_dump(mode="json")},
        )
        review = prepare_dictionary_import(path, self.core)

        with patch(
            "voiceger_editor.user_dictionary._atomic_write",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(Exception, "could not be persisted"):
                review.commit(self.core)

        self.assertEqual(self.core.list_japanese_entries(), before_entries)
        self.assertEqual(self.core.japanese_path.read_bytes(), before_file)
        self.assertEqual(self.backend.active, before_active)
        self.assertIn(existing_uuid, before_entries)

    def test_english_review_and_atomic_commit_preserve_existing_position(self):
        self.core.add_english_entry("Alpha", ["AE1", "L", "F", "AH0"])
        self.core.add_english_entry("Beta", ["B", "EY1", "T", "AH0"])
        path = self.write_json(
            "english.json",
            {
                "Alpha": ["AE1", "L", "F", "AH0"],
                "BETA": ["B", "IY1", "T", "AH0"],
                "Gamma": ["G", "AE1", "M", "AH0"],
            },
        )

        review = prepare_dictionary_import(path, self.core)
        self.assertIsInstance(review, EnglishDictionaryImportReview)
        self.assertEqual(review.exact_duplicate_count, 1)
        self.assertEqual(len(review.items), 2)
        by_surface = {item.incoming.surface: item for item in review.items}
        self.assertIs(by_surface["BETA"].relation, DictionaryImportRelation.CONFLICT)
        self.assertFalse(by_surface["BETA"].selected)
        self.assertIs(by_surface["Gamma"].relation, DictionaryImportRelation.NEW)
        self.assertTrue(by_surface["Gamma"].selected)

        review.set_selected("BETA", True)
        result = review.commit(self.core)

        self.assertEqual((result.imported, result.replaced, result.skipped), (1, 1, 1))
        entries = self.core.list_english_entries()
        self.assertEqual(list(entries), ["Alpha", "BETA", "Gamma"])
        self.assertEqual(entries["BETA"].phonemes, ["B", "IY1", "T", "AH0"])

    def test_english_import_is_atomic_on_persistence_failure(self):
        self.core.add_english_entry("Alpha", ["AE1", "L", "F", "AH0"])
        before_entries = self.core.list_english_entries()
        before_file = self.core.english_path.read_bytes()
        path = self.write_json(
            "atomic-english.json",
            {"Beta": ["B", "EY1", "T", "AH0"]},
        )
        review = prepare_dictionary_import(path, self.core)

        with patch(
            "voiceger_editor.user_dictionary._atomic_write",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(Exception, "could not be persisted"):
                review.commit(self.core)

        self.assertEqual(self.core.list_english_entries(), before_entries)
        self.assertEqual(self.core.english_path.read_bytes(), before_file)


if __name__ == "__main__":
    unittest.main()
