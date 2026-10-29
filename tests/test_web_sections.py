"""Slice 6b: protected spoken section text, append and delete API contract."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_web_mixed_pronunciation import GROUPS, MixedFake
from tests.test_web_takes import TOKEN
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.web import create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


class WebSectionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "saved"
        self.provider_calls = []
        self.fake = None

        def factory(caption):
            self.fake = MixedFake(caption, self.output)
            return self.fake

        def provider(text):
            self.provider_calls.append(text)
            groups = {
                "very sweet!": GROUPS,
                "very nice sweet!": (
                    ("very", ("V", "EH1", "R", "IY0")),
                    ("nice", ("N", "AY1", "S")),
                    ("sweet", ("S", "W", "IY1", "T")),
                    ("!", ("!",)),
                ),
                "hello": (("hello", ("HH", "AH1", "L", "OW0")),),
            }
            if text not in groups:
                raise ValueError("G2P unavailable")
            return groups[text]

        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.terms = patch("voiceger_editor.web_takes.require_current_acceptance")
        self.auth.start()
        self.terms.start()
        self.service = WebSessionOperations(caption_factory=factory,
                                            english_group_provider=provider)
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        self.sid = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        self.root = f"/api/web/sessions/{self.sid}"
        created = self.client.post(self.root + "/batch/items?expected_revision=0",
                                   headers=self.write, json={"text": "字幕の文章"})
        self.assertEqual(created.status_code, 200, created.text)
        self.item_id = created.json()["items"][0]["id"]
        self.path = self.root + "/batch/items/" + self.item_id
        self.finish(self.request("POST", "/audio/prepare", {"rebuild": False}))

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.terms.stop()
        self.auth.stop()
        self.temp.cleanup()

    def batch(self):
        response = self.client.get(self.root + "/batch", headers=self.read)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def request(self, method, suffix, payload=None, revision=None, headers=None):
        if revision is None:
            revision = self.batch()["revision"]
        return self.client.request(method, self.path + suffix +
                                   ("&" if "?" in suffix else "?") +
                                   "expected_revision=" + str(revision),
                                   json=payload,
                                   headers=self.write if headers is None else headers)

    def finish(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        op_id = response.json()["id"]
        for _ in range(300):
            op = self.client.get(self.root + "/operations/" + op_id,
                                 headers=self.read).json()
            if op["status"] not in ("running", "cancelling"):
                return op
            time.sleep(.005)
        self.fail("Web worker timed out")

    def test_english_text_preview_and_apply_retain_manual_word_edits(self):
        change_stress = self.request(
            "PATCH", "/pronunciation/english/1/0",
            {"opening": "V EH1 R IY0", "notation": "V EH0 R IY1"})
        self.assertTrue(change_stress.json()["changed"])
        original = deepcopy(self.fake.query.model_dump())
        draft = dict(language="en", index=1, opening="very sweet!",
                     text="very nice sweet!")
        op = self.finish(self.request("POST", "/sections/text/preview", draft))
        self.assertEqual(op["status"], "succeeded")
        self.assertEqual(len(self.fake.preview_queries[-1].voicegerSegments), 1)
        self.assertEqual(self.fake.preview_queries[-1].voicegerSegments[0].phonemes[:4],
                         ["V", "EH0", "R", "IY1"])
        self.assertEqual(self.fake.query.model_dump(), original)
        result = self.request("PATCH", "/sections/text", draft)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["changed"])
        en = self.batch()["items"][0]["pronunciation_sections"][1]
        self.assertEqual(en["text"], "very nice sweet!")
        self.assertEqual(en["groups"][0]["notation"], "V EH0 R IY1")
        self.assertEqual(en["groups"][1]["label"], "nice")
        self.assertEqual([s["text"] for s in self.batch()["items"][0]
                          ["pronunciation_sections"]], ["雨", "very nice sweet!", "咲く"])
        self.assertEqual(self.batch()["items"][0]["caption"], "字幕の文章")
        self.assertEqual(self.request("PATCH", "/sections/text", {
            **draft, "opening": "very sweet!", "text": "very sweet!"
        }).status_code, 422)

    def test_japanese_section_rebuild_reindexes_without_touching_other_sections(self):
        old = deepcopy(self.fake.query)
        with patch("voiceger_editor.query_editing.text_to_pronunciation",
                   return_value=parse_pronunciation("ミ'ズ/サ'ク！")):
            result = self.request("PATCH", "/sections/text", {
                "language": "ja", "index": 0, "opening": "雨", "text": "水が咲く"
            })
        self.assertEqual(result.status_code, 200, result.text)
        updated = self.fake.query
        self.assertEqual(updated.voicegerSegments[0].text, "水が咲く")
        self.assertEqual(updated.voicegerSegments[0].accentPhraseCount, 2)
        self.assertEqual(updated.voicegerSegments[2].accentPhraseStart, 2)
        self.assertEqual(updated.voicegerSegments[1].model_dump(),
                         old.voicegerSegments[1].model_dump())
        self.assertEqual(updated.voicegerSegments[2].text, "咲く")
        self.assertEqual(self.fake.caption, "字幕の文章")

    def test_noop_preserves_accepted_takes_and_changed_append_invalidates(self):
        self.finish(self.request("POST", "/takes/generate"))
        self.finish(self.request("POST", "/takes/1/accept"))
        saved = sorted((p.name, p.read_bytes()) for p in self.output.iterdir())
        before = self.batch()
        noop = self.request("PATCH", "/sections/text",
                            {"language": "en", "index": 1,
                             "opening": "very sweet!", "text": "very sweet!"})
        self.assertEqual(noop.status_code, 200, noop.text)
        self.assertFalse(noop.json()["changed"])
        self.assertEqual(self.batch(), before)
        add = self.request("POST", "/sections", {"language": "en", "text": "hello"})
        self.assertEqual(add.status_code, 200, add.text)
        self.assertEqual([x["language"] for x in add.json()["batch"]["items"][0]
                          ["pronunciation_sections"]], ["ja", "en", "ja", "en"])
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 0)
        self.assertEqual(self.batch()["items"][0]["accepted_take_numbers"], [])
        self.assertEqual(sorted((p.name, p.read_bytes()) for p in self.output.iterdir()), saved)

    def test_append_japanese_and_delete_section_shift_groupings(self):
        self.batch()  # Initial grouping cache on EN index 1.
        with patch("voiceger_editor.query_editing.text_to_pronunciation",
                   return_value=parse_pronunciation("オ'ト。")):
            add = self.request("POST", "/sections", {"language": "ja", "text": "音"})
        self.assertEqual(add.status_code, 200, add.text)
        self.assertEqual(self.fake.query.voicegerSegments[3].accentPhraseStart, 2)
        before = self.fake.query.voicegerSegments[1].phonemes[:]
        deleted = self.request("POST", "/sections/delete",
                               {"language": "ja", "index": 0, "opening": "雨"})
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.fake.query.voicegerSegments[0].language, "en")
        self.assertEqual(self.fake.query.voicegerSegments[0].phonemes, before)
        self.assertEqual(self.fake.query.voicegerSegments[2].accentPhraseStart, 1)
        cache = self.service._sessions[self.sid].english_groupings
        self.assertIn((self.item_id, 0), cache)
        self.assertNotIn((self.item_id, 1), cache)

    def test_deletion_down_to_only_japanese_and_pure_append(self):
        self.assertEqual(self.request("POST", "/sections/delete",
            {"language": "en", "index": 1, "opening": "very sweet!"}).status_code, 200)
        self.assertEqual(self.request("POST", "/sections/delete",
            {"language": "ja", "index": 0, "opening": "雨"}).status_code, 200)
        self.assertIsNone(self.fake.query.voicegerSegments)
        self.assertEqual(self.fake.pure_japanese_utterance_text, "咲く")
        prior = self.fake.query.accent_phrases[0].model_dump()
        self.assertEqual(self.request("POST", "/sections/delete",
            {"language": "ja", "index": 0, "opening": "咲く"}).status_code, 422)
        add = self.request("POST", "/sections",
                           {"language": "en", "text": "hello"})
        self.assertEqual(add.status_code, 200, add.text)
        self.assertEqual(self.fake.query.voicegerSegments[0].text, "咲く")
        self.assertEqual(self.fake.query.accent_phrases[0].model_dump(), prior)
        self.assertEqual(self.fake.query.voicegerSegments[1].language, "en")

    def test_stale_revision_wrong_section_invalid_and_busy_are_atomic(self):
        before = self.fake.query.model_dump()
        old = self.batch()["revision"]
        invalid = [
            ("PATCH", "/sections/text", {"language": "ja", "index": 1,
                "opening": "very sweet!", "text": "文"}, 422),
            ("PATCH", "/sections/text", {"language": "en", "index": 1,
                "opening": "outdated", "text": "hello"}, 422),
            ("PATCH", "/sections/text", {"language": "en", "index": 1,
                "opening": "very sweet!", "text": "bad\nline"}, 422),
            ("POST", "/sections", {"language": "en", "text": "nonsense"}, 422),
            ("POST", "/sections/delete", {"language": "en", "index": 99,
                "opening": "very sweet!"}, 422),
        ]
        for method, route, payload, code in invalid:
            with self.subTest(payload=payload):
                response = self.request(method, route, payload)
                self.assertEqual(response.status_code, code, response.text)
                self.assertEqual(self.fake.query.model_dump(), before)
        self.assertEqual(self.request("POST", "/sections",
            {"language": "en", "text": "hello"}, headers=self.read).status_code, 403)
        self.service._active = ("another-session", "some-operation")
        self.assertEqual(self.request("POST", "/sections",
            {"language": "en", "text": "hello"}).status_code, 409)
        self.service._active = None
        ok = self.request("POST", "/sections",
            {"language": "en", "text": "hello"})
        self.assertEqual(ok.status_code, 200, ok.text)
        stale = self.request("POST", "/sections/delete",
            {"language": "en", "index": 1, "opening": "very sweet!"},
            revision=old)
        self.assertEqual(stale.status_code, 409, stale.text)
