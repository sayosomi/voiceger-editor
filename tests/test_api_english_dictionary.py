"""HTTP contract tests for the Voiceger Editor English user dictionary."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from voiceger_editor import api
from voiceger_editor.mixed_language import DetectedSegment
from voiceger_editor.user_dictionary import UserDictionaryCore


class ApiEnglishUserDictionaryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.core = UserDictionaryCore(
            root / "voiceger",
            data_directory=root / "config",
            openjtalk_dictionary=Mock(),
        )
        self.adapter = SimpleNamespace(
            user_dictionary=self.core,
            ensure_japanese_dictionary_active=Mock(),
            english_phonemes=lambda text: (
                self.core.lookup_english_entry(text)
                or ["HH", "AH0", "L", "OW1"]
            ),
        )
        adapter_patch = patch(
            "voiceger_editor.api.get_adapter", return_value=self.adapter
        )
        adapter_patch.start()
        self.addCleanup(adapter_patch.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def test_index_exposes_all_english_dictionary_routes(self):
        endpoints = self.client.get("/").json()["endpoints"]
        for route in (
            "GET /english_user_dict",
            "POST /english_user_dict_word",
            "PUT /english_user_dict_word/{surface}",
            "DELETE /english_user_dict_word/{surface}",
            "POST /import_english_user_dict",
        ):
            self.assertIn(route, endpoints)

    def test_create_list_update_delete_and_persistence(self):
        entry = {"surface": "sweet", "phonemes": ["S", "W", "IY1", "T"]}
        created = self.client.post("/english_user_dict_word", json=entry)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json(), entry)
        self.assertEqual(self.client.get("/english_user_dict").json(), {
            "sweet": entry["phonemes"]
        })
        self.assertTrue(self.core.english_path.exists())
        self.assertEqual(
            self.core.english_path.read_text(encoding="utf-8").strip().startswith("{"),
            True,
        )

        updated = self.client.put(
            "/english_user_dict_word/SWEET",
            json={"surface": "Sweets", "phonemes": ["S", "W", "IY1", "T", "S"]},
        )
        self.assertEqual(updated.status_code, 204, updated.text)
        self.assertEqual(self.client.get("/english_user_dict").json(), {
            "Sweets": ["S", "W", "IY1", "T", "S"]
        })
        self.assertEqual(
            self.client.delete("/english_user_dict_word/sWeEtS").status_code,
            204,
        )
        self.assertEqual(self.client.get("/english_user_dict").json(), {})

    def test_post_replaces_existing_case_insensitive_surface(self):
        for surface, tokens in (
            ("Voiceger", ["V", "OY1", "AH0", "JH", "ER0"]),
            ("VOICEGER", ["V", "OY1", "JH", "ER0"]),
        ):
            response = self.client.post(
                "/english_user_dict_word",
                json={"surface": surface, "phonemes": tokens},
            )
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.client.get("/english_user_dict").json(),
            {"VOICEGER": ["V", "OY1", "JH", "ER0"]},
        )

    def test_import_native_json_respects_override_and_validates_atomically(self):
        self.assertEqual(self.client.post(
            "/english_user_dict_word",
            json={"surface": "hello", "phonemes": ["HH", "AH0", "L", "OW1"]},
        ).status_code, 200)
        incoming = {
            "HELLO": ["HH", "EH1", "L", "OW0"],
            "sweet": ["S", "W", "IY1", "T"],
        }
        self.assertEqual(self.client.post(
            "/import_english_user_dict", json=incoming
        ).status_code, 204)
        self.assertEqual(self.client.get("/english_user_dict").json(), {
            "hello": ["HH", "AH0", "L", "OW1"],
            "sweet": ["S", "W", "IY1", "T"],
        })
        self.assertEqual(self.client.post(
            "/import_english_user_dict?override=true", json=incoming
        ).status_code, 204)
        self.assertEqual(self.client.get("/english_user_dict").json(), {
            "HELLO": incoming["HELLO"],
            "sweet": incoming["sweet"],
        })
        invalid = self.client.post(
            "/import_english_user_dict",
            json={"valid": ["V", "AE1", "L", "IH0", "D"], "bad": ["INVALID"]},
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("valid", self.client.get("/english_user_dict").json())

    def test_rejects_invalid_phonemes_and_missing_or_conflicting_surface(self):
        invalid = self.client.post(
            "/english_user_dict_word",
            json={"surface": "bad", "phonemes": ["NOPE"]},
        )
        self.assertEqual(invalid.status_code, 422)
        missing = self.client.delete("/english_user_dict_word/not-found")
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(
            self.client.put(
                "/english_user_dict_word/not-found",
                json={"surface": "new", "phonemes": ["N", "UW1"]},
            ).status_code, 422
        )
        for surface in ("one", "two"):
            self.assertEqual(self.client.post(
                "/english_user_dict_word",
                json={"surface": surface, "phonemes": ["W", "AH1", "N"]},
            ).status_code, 200)
        conflict = self.client.put(
            "/english_user_dict_word/one",
            json={"surface": "TWO", "phonemes": ["T", "UW1"]},
        )
        self.assertEqual(conflict.status_code, 422)
        self.assertEqual(len(self.client.get("/english_user_dict").json()), 2)

    def test_failed_persistence_returns_stable_500_and_preserves_entries(self):
        with patch(
            "voiceger_editor.user_dictionary._atomic_write",
            side_effect=OSError("disk full"),
        ):
            result = self.client.post(
                "/english_user_dict_word",
                json={"surface": "sweet", "phonemes": ["S", "W", "IY1", "T"]},
            )
        self.assertEqual(result.status_code, 500)
        self.assertEqual(
            result.json()["detail"],
            "English user dictionary could not be updated.",
        )
        self.assertEqual(self.client.get("/english_user_dict").json(), {})

    def test_api_dictionary_edit_changes_next_english_audio_query(self):
        with patch(
            "voiceger_editor.api._resolve_style", return_value=object()
        ), patch(
            "voiceger_editor.mixed_language.detect_language_segments",
            return_value=[DetectedSegment("en", "sweet")],
        ):
            before = self.client.post(
                "/audio_query", params={"text": "sweet", "speaker": 3}
            )
            self.assertEqual(before.status_code, 200, before.text)
            self.assertEqual(before.json()["voicegerSegments"][0]["phonemes"], [
                "HH", "AH0", "L", "OW1",
            ])
            self.assertEqual(self.client.post(
                "/english_user_dict_word",
                json={"surface": "sweet", "phonemes": ["S", "W", "IY1", "T"]},
            ).status_code, 200)
            after = self.client.post(
                "/audio_query", params={"text": "sweet", "speaker": 3}
            )
            self.assertEqual(after.status_code, 200, after.text)
            self.assertEqual(
                after.json()["voicegerSegments"][0]["phonemes"],
                ["S", "W", "IY1", "T"],
            )
            self.assertEqual(
                before.json()["voicegerSegments"][0]["phonemes"],
                ["HH", "AH0", "L", "OW1"],
            )


if __name__ == "__main__":
    unittest.main()
