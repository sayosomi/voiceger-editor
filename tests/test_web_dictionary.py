"""Web Slice 8 dictionary API, persistence, stale edits and Preview isolation."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.test_user_dictionary import FakeBackend
from voiceger_editor.user_dictionary import UserDictionaryCore
from voiceger_editor.web import create_web_app
from voiceger_editor.web_sessions import WebSessionOperations

TOKEN = "dictionary-web-test-token-long-enough-320"


class DictionaryWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "voiceger").mkdir()
        self.core = UserDictionaryCore(root / "voiceger", data_directory=root / "data",
                                       openjtalk_dictionary=FakeBackend())
        self.token = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.terms = patch("voiceger_editor.web_takes.require_current_acceptance")
        self.token.start()
        self.terms.start()
        self.service = WebSessionOperations(dictionary_core=self.core,
            dictionary_preview_provider=lambda surface, query:
                {"audio": [0.0] * 1000, "sampling_rate": 32000})
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        self.sid = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        self.base = f"/api/web/sessions/{self.sid}/dictionary"

    def tearDown(self):
        self.client.close()
        self.service.shutdown()
        self.terms.stop()
        self.token.stop()
        self.tmp.cleanup()

    def listing(self, lang="ja", query=""):
        result = self.client.get(self.base + "/" + lang,
            params={"query": query}, headers=self.read)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def save(self, lang, surface, notation, identity=None, revision=None, **kwargs):
        data = dict(expected_revision=revision or self.listing(lang)["revision"],
                    language=lang, surface=surface, notation=notation, **kwargs)
        return self.client.request("PUT" if identity else "POST",
            self.base + "/words" + ("/" + identity if identity else ""),
            json=data, headers=self.write)

    def test_japanese_multi_peak_crud_and_conflicts(self):
        self.assertEqual(self.listing()["total"], 0)
        added = self.save("ja", "四国めたん", "[シ]コク[メ]タン")
        self.assertEqual(added.status_code, 200, added.text)
        identity = added.json()["id"]
        self.assertEqual(self.listing()["entries"][0]["notation"], "[シ]コク[メ]タン")
        self.assertEqual(self.listing(query="メタン")["shown"], 1)
        self.assertEqual(len(self.core.get_japanese_pitch_events(identity)), 3)
        stale_revision = self.listing()["revision"]
        self.assertFalse(self.save("ja", "四国めたん",
            "[シ]コク[メ]タン", identity).json()["changed"])
        update = self.save("ja", "四国めたん", "シ'コクメタン", identity)
        self.assertEqual(update.status_code, 200, update.text)
        self.assertFalse(self.core.get_japanese_pitch_events(identity))
        self.assertEqual(self.save("ja", "四国めたん", "シ'コクメタン",
            identity, revision=stale_revision).status_code, 409)
        self.assertEqual(self.save("ja", "雷", "カ'ミ ナリ").status_code, 422)
        self.assertEqual(self.save("ja", "雷", "カ'ミ。").status_code, 422)
        self.assertEqual(self.save("ja", "四国めたん", "シ'コクメタン").status_code, 422)
        deleted = self.client.delete(self.base + "/words/" + identity,
            params={"language": "ja", "expected_revision": self.listing()["revision"]},
            headers=self.write)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.listing()["total"], 0)

    def test_english_stress_casefold_and_rename_collision(self):
        first = self.save("en", "sweet", "S W IY1 T")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.save("en", "SWEET", "S W IY1 T").status_code, 422)
        self.assertEqual(self.save("en", "other", "AH1 DH ER0").status_code, 200)
        self.assertEqual(self.save("en", "other", "S W IY1 T", "sweet").status_code, 422)
        changed = self.save("en", "Sweet", "S W IY2 T", "sweet")
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(self.core.lookup_english_entry("SWEET"), ["S", "W", "IY2", "T"])
        self.assertEqual(self.listing("en", query="IY2")["shown"], 1)

    def test_auth_origin_and_uncommitted_preview(self):
        self.assertEqual(self.client.get(self.base + "/ja").status_code, 401)
        before = self.listing()
        payload = dict(expected_revision=before["revision"], language="ja",
                       surface="雨", notation="ア'メ")
        self.assertEqual(self.client.post(self.base + "/words",
            json=payload, headers=self.read).status_code, 403)
        self.assertEqual(self.client.post(self.base + "/words",
            json=payload, headers={**self.write,
                "Origin": "https://evil.example"}).status_code, 403)
        start = self.client.post(self.base + "/pronunciation/preview",
            headers=self.write, json={"language": "ja", "surface": "雨",
                                      "notation": "アメ'"})
        self.assertEqual(start.status_code, 202, start.text)
        for _ in range(150):
            op = self.client.get(f"/api/web/sessions/{self.sid}/operations/" +
                start.json()["id"], headers=self.read).json()
            if op["status"] != "running":
                break
            time.sleep(0.01)
        self.assertEqual(op["status"], "succeeded", op)
        self.assertEqual(self.listing(), before)
        wav = self.client.get(self.base + "/audio/preview/" +
            op["result"]["preview_id"], headers=self.read)
        self.assertEqual(wav.status_code, 200)
        self.assertTrue(wav.content.startswith(b"RIFF"))

    def test_legacy_accent_zero_and_session_persistence(self):
        uid = self.core.add_japanese_word(surface="アメ",
            pronunciation="アメ", accent_type=0)
        self.assertEqual(self.listing()["entries"][0]["notation"], "アメ'")
        result = self.save("ja", "アメ", "アメ'", uid)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()["changed"])
        self.assertEqual(self.core.list_japanese_entries()[uid].accent_type, 0)
        sid = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        response = self.client.get(f"/api/web/sessions/{sid}/dictionary/ja",
            headers=self.read)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["entries"][0]["notation"], "アメ'")


    def test_direct_apply_validation_is_authenticated_noncommitting_and_language_specific(self):
        original = self.listing()
        url = self.base + "/pronunciation/validate"
        draft = {"language": "ja", "surface": "四国めたん",
                 "notation": "[シ]コク[メ]タン"}
        denied = self.client.post(url, json=draft, headers=self.read)
        self.assertEqual(denied.status_code, 403)
        denied = self.client.post(url, json=draft,
            headers={**self.write, "Origin": "https://attacker.example"})
        self.assertEqual(denied.status_code, 403)
        accepted = self.client.post(url, json=draft, headers=self.write)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertTrue(accepted.json()["valid"])
        invalid = [
            {"language": "ja", "surface": "四国めたん", "notation": "シ'コク メタン"},
            {"language": "ja", "surface": "四国めたん", "notation": "シ'コク。"},
            {"language": "ja", "surface": "四国めたん", "notation": ""},
            {"language": "en", "surface": "test", "notation": "AH9"},
            {"language": "en", "surface": "test", "notation": ""},
        ]
        for rejected in invalid:
            with self.subTest(rejected=rejected):
                self.assertEqual(self.client.post(
                    url, json=rejected, headers=self.write).status_code, 422)
        english = self.client.post(url, json={
            "language": "en", "surface": "happy", "notation": "HH AE1 P IY0",
        }, headers=self.write)
        self.assertEqual(english.status_code, 200, english.text)
        self.assertEqual(self.listing(), original)
        self.assertEqual(self.listing("en")["total"], 0)

if __name__ == "__main__":
    unittest.main()
