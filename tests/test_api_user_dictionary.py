from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from voiceger_editor import api
from voiceger_editor.openjtalk_dictionary import OpenJTalkDictionaryError
from voiceger_editor.user_dictionary import UserDictionaryCore
from voiceger_editor.voicevox_api_models import AudioQuery


class _State:
    def __init__(self, entries):
        self.entries = dict(entries)
        self.compilation = None
        self.signature = None


class FakeBackend:
    def __init__(self):
        self.active = {}
        self.fail_next = False

    def ensure_active(self, entries, *, force=False):
        return None

    def snapshot(self):
        return _State(self.active)

    def activate_entries(self, entries):
        if self.fail_next:
            self.fail_next = False
            raise OpenJTalkDictionaryError("test compile failure")
        previous = self.snapshot()
        self.active = dict(entries)
        return previous

    def restore(self, state):
        self.active = dict(state.entries)

    def commit(self, previous):
        return None


class ApiUserDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        backend = FakeBackend()
        self.core = UserDictionaryCore(
            self.root / "voiceger",
            data_directory=self.root / "config",
            openjtalk_dictionary=backend,
        )
        self.adapter = SimpleNamespace(
            voiceger_root=self.root / "voiceger",
            character_name="ずんだもん",
            user_dictionary=self.core,
            english_phonemes=Mock(return_value=["HH", "AH0"]),
            ensure_japanese_dictionary_active=Mock(),
        )
        self.backend = backend
        self.client = TestClient(api.app)
        self.adapter_patch = patch("voiceger_editor.api.get_adapter", return_value=self.adapter)
        self.adapter_patch.start()
        self.addCleanup(self.adapter_patch.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_root_lists_all_five_dictionary_endpoints(self):
        endpoints = self.client.get("/").json()["endpoints"]
        for endpoint in (
            "GET /user_dict",
            "POST /user_dict_word",
            "PUT /user_dict_word/{word_uuid}",
            "DELETE /user_dict_word/{word_uuid}",
            "POST /import_user_dict",
        ):
            self.assertIn(endpoint, endpoints)

    def test_create_list_update_delete_uses_shared_canonical_model(self):
        response = self.client.post(
            "/user_dict_word",
            params={
                "surface": "ずんだもん",
                "pronunciation": "ズンダモン",
                "accent_type": 3,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        word_uuid = response.json()
        listed = self.client.get("/user_dict")
        self.assertEqual(listed.status_code, 200)
        word = listed.json()[word_uuid]
        self.assertEqual(
            set(word),
            {
                "surface",
                "priority",
                "context_id",
                "part_of_speech",
                "part_of_speech_detail_1",
                "part_of_speech_detail_2",
                "part_of_speech_detail_3",
                "inflectional_type",
                "inflectional_form",
                "stem",
                "yomi",
                "pronunciation",
                "accent_type",
                "mora_count",
                "accent_associative_rule",
            },
        )
        self.assertEqual(word["priority"], 5)
        self.assertEqual(word["context_id"], 1348)
        self.assertNotIn("word_type", word)

        updated = self.client.put(
            f"/user_dict_word/{word_uuid}",
            params={
                "surface": "ずんだもん",
                "pronunciation": "ズンダモン",
                "accent_type": 2,
            },
        )
        self.assertEqual(updated.status_code, 204, updated.text)
        updated_word = self.client.get("/user_dict").json()[word_uuid]
        self.assertEqual(updated_word["accent_type"], 2)
        self.assertEqual(updated_word["priority"], 5)
        self.assertEqual(updated_word["context_id"], 1348)

        deleted = self.client.delete(f"/user_dict_word/{word_uuid}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get("/user_dict").json(), {})

    def test_import_accepts_vox_userdict_shape_and_honors_override(self):
        word_uuid = self.client.post(
            "/user_dict_word",
            params={
                "surface": "既存",
                "pronunciation": "キソン",
                "accent_type": 2,
            },
        ).json()
        import_word = {
            "surface": "別の語",
            "priority": 4,
            "context_id": 1348,
            "part_of_speech": "名詞",
            "part_of_speech_detail_1": "固有名詞",
            "part_of_speech_detail_2": "一般",
            "part_of_speech_detail_3": "*",
            "inflectional_type": "*",
            "inflectional_form": "*",
            "stem": "*",
            "yomi": "アメ",
            "pronunciation": "アメ",
            "accent_type": 1,
            "mora_count": 2,
            "accent_associative_rule": "*",
        }
        keep = self.client.post(
            "/import_user_dict",
            params={"override": "false"},
            json={word_uuid: import_word},
        )
        self.assertEqual(keep.status_code, 204, keep.text)
        self.assertEqual(self.client.get("/user_dict").json()[word_uuid]["surface"], "既存")
        replace = self.client.post(
            "/import_user_dict",
            params={"override": "true"},
            json={word_uuid: import_word},
        )
        self.assertEqual(replace.status_code, 204, replace.text)
        self.assertEqual(
            self.client.get("/user_dict").json()[word_uuid]["surface"],
            "別の語",
        )

    def test_invalid_fields_and_uuid_return_deterministic_422(self):
        invalid_pronunciation = self.client.post(
            "/user_dict_word",
            params={
                "surface": "語",
                "pronunciation": "ひらがな",
                "accent_type": 1,
            },
        )
        self.assertEqual(invalid_pronunciation.status_code, 422)
        self.assertIn("発音", invalid_pronunciation.json()["detail"])

        for params in (
            {"surface": "語", "pronunciation": "ゴ", "accent_type": 2},
            {"surface": "語", "pronunciation": "ゴ", "accent_type": 1, "priority": 11},
            {"surface": "語", "pronunciation": "ゴ", "accent_type": 1, "word_type": "ADVERB"},
        ):
            with self.subTest(params=params):
                response = self.client.post("/user_dict_word", params=params)
                self.assertEqual(response.status_code, 422)

        malformed = self.client.delete("/user_dict_word/not-a-uuid")
        missing = self.client.delete("/user_dict_word/00000000-0000-0000-0000-000000000001")
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(malformed.json()["detail"], "invalid word UUID")
        self.assertEqual(missing.json()["detail"], "UUIDに該当するワードが見つかりませんでした")

    def test_compilation_failure_maps_to_stable_500(self):
        self.backend.fail_next = True
        response = self.client.post(
            "/user_dict_word",
            params={"surface": "語", "pronunciation": "ゴ", "accent_type": 1},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "Japanese user dictionary could not be updated.",
        )
        self.assertEqual(self.client.get("/user_dict").json(), {})

    def test_query_activates_dictionary_before_normal_construction(self):
        order = []
        self.adapter.ensure_japanese_dictionary_active.side_effect = lambda: order.append("activate")
        query_value = AudioQuery(accent_phrases=[])
        with patch("voiceger_editor.api._resolve_style", return_value=object()), patch(
            "voiceger_editor.api.build_mixed_audio_query",
            side_effect=lambda *args, **kwargs: order.append("query") or query_value,
        ):
            response = self.client.post(
                "/audio_query",
                params={"text": "明日は雨", "speaker": 3},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(order, ["activate", "query"])


if __name__ == "__main__":
    unittest.main()
