import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from voiceger_editor.dictionary_export import (
    export_voiceger_editor_dictionaries,
    export_voicevox_dictionary,
)
from voiceger_editor.openjtalk_dictionary import expand_word_type
from voiceger_editor.user_dictionary import (
    EnglishUserDictionaryEntry,
    JapaneseWordType,
    UserDictWord,
)


def japanese_word(surface, pronunciation, accent):
    return UserDictWord.model_validate(
        {
            "surface": surface,
            "priority": 5,
            **expand_word_type(JapaneseWordType.PROPER_NOUN.value),
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
        self.japanese = {
            "22222222-2222-4222-8222-222222222222": japanese_word(
                "ずんだもん", "ズンダモン", 3
            ),
            "11111111-1111-4111-8111-111111111111": japanese_word(
                "雨", "アメ", 1
            ),
        }
        self.english = {
            "zebra": EnglishUserDictionaryEntry(
                surface="zebra",
                phonemes=["Z", "IY1", "B", "R", "AH0"],
            ),
            "Apple": EnglishUserDictionaryEntry(
                surface="Apple",
                phonemes=["AE1", "P", "AH0", "L"],
            ),
        }

    def list_japanese_entries(self):
        return dict(self.japanese)

    def list_english_entries(self):
        return dict(self.english)


class DictionaryExportTests(unittest.TestCase):
    timestamp = datetime(2026, 10, 6, 1, 2)

    def test_voiceger_pair_preserves_order_and_uses_one_collision_suffix(self):
        core = FakeDictionaryCore()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing = output_dir / "202610060102_english_user_dict.json"
            existing.write_text("existing", encoding="utf-8")

            result = export_voiceger_editor_dictionaries(
                core,
                output_dir,
                timestamp=self.timestamp,
            )

            self.assertEqual(
                [path.name for path in result.paths],
                [
                    "202610060102_user_dict-2.json",
                    "202610060102_english_user_dict-2.json",
                ],
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing")
            self.assertFalse(
                (output_dir / "202610060102_user_dict.json").exists()
            )

            japanese = json.loads(result.paths[0].read_text(encoding="utf-8"))
            english = json.loads(result.paths[1].read_text(encoding="utf-8"))
            self.assertEqual(list(japanese), list(core.japanese))
            self.assertEqual(list(english), list(core.english))

    def test_voicevox_export_is_japanese_only_and_collision_safe(self):
        core = FakeDictionaryCore()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "nested"
            output_dir.mkdir()
            existing = output_dir / "202610060102_voicevox_user_dict.json"
            existing.write_text("existing", encoding="utf-8")

            result = export_voicevox_dictionary(
                core,
                output_dir,
                timestamp=self.timestamp,
            )

            self.assertEqual(
                [path.name for path in result.paths],
                ["202610060102_voicevox_user_dict-2.json"],
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing")
            self.assertFalse(
                (output_dir / "202610060102_english_user_dict-2.json").exists()
            )
            payload = json.loads(result.paths[0].read_text(encoding="utf-8"))
            self.assertEqual(list(payload), list(core.japanese))
            first = payload[next(iter(payload))]
            self.assertIn("surface", first)
            self.assertIn("part_of_speech", first)
            self.assertIn("accent_type", first)

    def test_failed_pair_write_removes_only_files_owned_by_attempt(self):
        core = FakeDictionaryCore()
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with patch(
                "voiceger_editor.dictionary_export._write_payload",
                side_effect=[None, OSError("write failed")],
            ):
                with self.assertRaisesRegex(OSError, "write failed"):
                    export_voiceger_editor_dictionaries(
                        core,
                        output_dir,
                        timestamp=self.timestamp,
                    )

            self.assertEqual(list(output_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
