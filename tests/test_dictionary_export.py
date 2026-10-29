import hashlib
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from voiceger_editor.dictionary_export import (
    export_voiceger_editor_dictionaries,
    export_voicevox_dictionary,
)
from voiceger_editor.openjtalk_dictionary import expand_word_type
from voiceger_editor.pronunciation import PitchEvent
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
        self.pitch = {}

    def list_japanese_entries(self):
        return dict(self.japanese)

    def list_english_entries(self):
        return dict(self.english)

    def list_japanese_pitch_events(self):
        return dict(self.pitch)


class DictionaryExportTests(unittest.TestCase):
    timestamp = datetime(2026, 10, 6, 1, 2)

    def test_native_zip_is_single_complete_collision_safe_archive(self):
        core = FakeDictionaryCore()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            existing = output / "202610060102_voiceger_editor_dictionary.zip"
            existing.write_text("existing", encoding="utf-8")
            result = export_voiceger_editor_dictionaries(
                core, output, timestamp=self.timestamp,
            )
            self.assertEqual(
                [path.name for path in result.paths],
                ["202610060102_voiceger_editor_dictionary-2.zip"],
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing")
            with ZipFile(result.paths[0]) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["manifest.json", "user_dict.json", "english_user_dict.json"],
                )
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["version"], 1)
                for name, digest in manifest["members"].items():
                    self.assertEqual(
                        hashlib.sha256(archive.read(name)).hexdigest(), digest
                    )
                japanese = json.loads(archive.read("user_dict.json"))
                english = json.loads(archive.read("english_user_dict.json"))
            self.assertEqual(list(japanese), list(core.japanese))
            self.assertEqual(list(english), list(core.english))
            self.assertCountEqual(list(output.iterdir()), [existing, result.paths[0]])

    def test_pitch_metadata_is_optional_and_stays_canonical(self):
        core = FakeDictionaryCore()
        core.japanese["33333333-3333-4333-8333-333333333333"] = japanese_word(
            "スタックチャン", "スタックチャン", 2
        )
        uuid = "33333333-3333-4333-8333-333333333333"
        core.pitch[uuid] = (
            PitchEvent(1, "["), PitchEvent(2, "]"),
            PitchEvent(4, "["), PitchEvent(5, "]"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = export_voiceger_editor_dictionaries(
                core, Path(directory), timestamp=self.timestamp
            ).paths[0]
            with ZipFile(path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [
                        "manifest.json", "user_dict.json",
                        "english_user_dict.json", "user_dict_pitch_events.json",
                    ],
                )
                metadata = json.loads(archive.read("user_dict_pitch_events.json"))
                self.assertEqual(
                    metadata["entries"][uuid]["events"],
                    [
                        {"afterMora": 1, "symbol": "["},
                        {"afterMora": 2, "symbol": "]"},
                        {"afterMora": 4, "symbol": "["},
                        {"afterMora": 5, "symbol": "]"},
                    ],
                )

    def test_failed_publication_never_leaves_an_incomplete_named_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch(
                "voiceger_editor.dictionary_export.os.link",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    export_voiceger_editor_dictionaries(
                        FakeDictionaryCore(), output, timestamp=self.timestamp
                    )
            self.assertEqual(list(output.iterdir()), [])

    def test_voicevox_export_is_still_japanese_json_and_collision_safe(self):
        core = FakeDictionaryCore()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            existing = output / "202610060102_voicevox_user_dict.json"
            existing.write_text("existing", encoding="utf-8")
            result = export_voicevox_dictionary(
                core, output, timestamp=self.timestamp
            )
            self.assertEqual(
                [path.name for path in result.paths],
                ["202610060102_voicevox_user_dict-2.json"],
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing")
            japanese = json.loads(result.paths[0].read_text(encoding="utf-8"))
            self.assertEqual(list(japanese), list(core.japanese))
            self.assertIn("part_of_speech", next(iter(japanese.values())))


if __name__ == "__main__":
    unittest.main()
