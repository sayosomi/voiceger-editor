"""Slice 6a: English direct ARPAbet and mixed Japanese Web behavior."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_web_pronunciation import JapaneseUtterance
from tests.test_web_takes import FakeUtterance, TOKEN
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.voicevox_api_models import AudioQuery, VoicegerSegment
from voiceger_editor.voicevox_query import build_audio_query
from voiceger_editor.web import create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


GROUPS = (
    ("very", ("V", "EH1", "R", "IY0")),
    ("sweet", ("S", "W", "IY1", "T")),
    ("!", ("!",)),
)


def mixed_query() -> AudioQuery:
    phrases = build_audio_query(
        pronunciation=parse_pronunciation("ア'メ/サ'ク。")
    ).accent_phrases
    return AudioQuery(
        accent_phrases=phrases, kana=None,
        voicegerSegments=[
            VoicegerSegment(language="ja", text="雨", accentPhraseStart=0,
                            accentPhraseCount=1, pronunciationTerminator="。"),
            VoicegerSegment(language="en", text="very sweet!",
                            phonemes=[p for _, tokens in GROUPS for p in tokens]),
            VoicegerSegment(language="ja", text="咲く", accentPhraseStart=1,
                            accentPhraseCount=1, pronunciationTerminator="。"),
        ],
    )


class MixedFake(JapaneseUtterance):
    def __init__(self, caption, output):
        super().__init__(caption, output)
        self._query = mixed_query()
        self.preview_queries = []

    def preview_synthesis(self, query):
        self.preview_queries.append(deepcopy(query))
        return FakeUtterance.preview_synthesis(self, query)


class MixedPronunciationWebTests(unittest.TestCase):
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
            if text != "very sweet!":
                raise ValueError("unavailable")
            return GROUPS

        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.terms = patch("voiceger_editor.web_takes.require_current_acceptance")
        self.auth.start()
        self.terms.start()
        self.service = WebSessionOperations(
            caption_factory=factory, english_group_provider=provider
        )
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        self.sid = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        self.root = f"/api/web/sessions/{self.sid}"
        created = self.client.post(self.root + "/batch/items?expected_revision=0",
                                   headers=self.write, json={"text": "雨 very sweet! 咲く"})
        self.assertEqual(created.status_code, 200, created.text)
        self.item_id = created.json()["items"][0]["id"]
        self.path = self.root + "/batch/items/" + self.item_id
        self.finish(self.action("POST", "/audio/prepare", {"rebuild": False}))

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

    def action(self, method, suffix, body=None, revision=None, headers=None):
        if revision is None:
            revision = self.batch()["revision"]
        join = "&" if "?" in suffix else "?"
        return self.client.request(
            method, self.path + suffix + join + "expected_revision=" + str(revision),
            json=body, headers=self.write if headers is None else headers,
        )

    def finish(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        op_id = response.json()["id"]
        for _ in range(200):
            result = self.client.get(self.root + "/operations/" + op_id, headers=self.read)
            self.assertEqual(result.status_code, 200, result.text)
            op = result.json()
            if op["status"] not in {"running", "cancelling"}:
                return op
            time.sleep(.005)
        self.fail("worker timed out")

    @staticmethod
    def english_payload(opening, draft):
        return {"opening": opening, "notation": draft}

    def test_snapshot_actual_order_and_english_word_rows(self):
        item = self.batch()["items"][0]
        self.assertIsNone(item["pronunciation"])
        sections = item["pronunciation_sections"]
        self.assertEqual([section["language"] for section in sections], ["ja", "en", "ja"])
        self.assertEqual([section["text"] for section in sections], ["雨", "very sweet!", "咲く"])
        self.assertEqual([s["notation"] for s in (sections[0], sections[2])],
                         ["ア'メ。", "サ'ク。"])
        self.assertEqual([(g["label"], g["notation"]) for g in sections[1]["groups"]],
                         [(label, " ".join(phones)) for label, phones in GROUPS])
        self.assertEqual(sections[1]["groups"][0]["display"], "V [EH1] R IY0")
        self.assertEqual(len(self.provider_calls), 1)

    def test_word_draft_preview_isolated_and_no_commit(self):
        before = self.batch()
        op = self.finish(self.action(
            "POST", "/pronunciation/english/1/0/preview",
            self.english_payload("V EH1 R IY0", "V EH0 R IY1"),
        ))
        self.assertEqual(op["status"], "succeeded")
        query = self.fake.preview_queries[-1]
        self.assertEqual(len(query.voicegerSegments), 1)
        self.assertEqual(query.voicegerSegments[0].phonemes[:4],
                         ["V", "EH0", "R", "IY1"])
        self.assertEqual(query.accent_phrases, [])
        self.assertEqual(self.batch(), before)
        self.assertFalse(self.output.exists())

    def test_noop_stress_edit_punctuation_and_saved_take_preserved(self):
        self.finish(self.action("POST", "/takes/generate"))
        self.finish(self.action("POST", "/takes/1/accept"))
        files = [(p.name, p.read_bytes()) for p in self.output.iterdir()]
        base = self.batch()
        no_op = self.action("PATCH", "/pronunciation/english/1/0",
                            self.english_payload("V EH1 R IY0", "v eh1 r iy0"))
        self.assertEqual(no_op.status_code, 200, no_op.text)
        self.assertFalse(no_op.json()["changed"])
        self.assertEqual(self.batch(), base)

        edit = self.action("PATCH", "/pronunciation/english/1/0",
                           self.english_payload("V EH1 R IY0", "V EH0 R IY1"))
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertTrue(edit.json()["changed"])
        item = self.batch()["items"][0]
        self.assertEqual(item["candidate_count"], 0)
        self.assertEqual(item["accepted_take_numbers"], [])
        self.assertEqual(item["pronunciation_sections"][1]["groups"][0]["notation"],
                         "V EH0 R IY1")
        self.assertEqual([(p.name, p.read_bytes()) for p in self.output.iterdir()], files)

        punct = self.action("PATCH", "/pronunciation/english/1/2",
                            self.english_payload("!", "?"))
        self.assertEqual(punct.status_code, 200, punct.text)
        self.assertEqual(self.batch()["items"][0]["pronunciation_sections"][1]
                         ["groups"][2]["label"], "?")
        self.assertEqual(len(self.provider_calls), 1)

    def test_changed_token_count_keeps_other_group_boundaries(self):
        edit = self.action("PATCH", "/pronunciation/english/1/0",
                           self.english_payload("V EH1 R IY0", "V IY1"))
        self.assertEqual(edit.status_code, 200, edit.text)
        sections = self.batch()["items"][0]["pronunciation_sections"]
        self.assertEqual(sections[1]["groups"][0]["notation"], "V IY1")
        self.assertEqual(sections[1]["groups"][1]["notation"], "S W IY1 T")
        self.assertEqual(len(self.provider_calls), 1)
        next_edit = self.action("PATCH", "/pronunciation/english/1/1",
                                self.english_payload("S W IY1 T", "S W IY2 T"))
        self.assertEqual(next_edit.status_code, 200, next_edit.text)
        self.assertEqual(self.fake.query.voicegerSegments[1].phonemes,
                         ["V", "IY1", "S", "W", "IY2", "T", "!"])

    def test_mixed_japanese_edits_only_selected_section(self):
        pre = deepcopy(self.fake.query)
        op = self.finish(self.action(
            "POST", "/pronunciation/preview?segment_index=2",
            {"notation": "サク'？"},
        ))
        self.assertEqual(op["status"], "succeeded")
        self.assertIsNone(self.fake.preview_queries[-1].voicegerSegments)
        self.assertEqual(self.fake.query.model_dump(), pre.model_dump())
        edit = self.action("PATCH", "/pronunciation?segment_index=2",
                           {"notation": "サク'？"})
        self.assertEqual(edit.status_code, 200, edit.text)
        after = self.fake.query
        self.assertEqual(after.voicegerSegments[1].phonemes,
                         pre.voicegerSegments[1].phonemes)
        self.assertEqual(self.batch()["items"][0]["pronunciation_sections"][0]
                         ["notation"], "ア'メ。")
        self.assertEqual(self.batch()["items"][0]["pronunciation_sections"][2]
                         ["notation"], "サク'？")

    def test_invalid_stale_unauthorized_and_busy_are_atomic(self):
        before = self.fake.query.model_dump()
        original_rev = self.batch()["revision"]
        suffix = "/pronunciation/english/1/0"
        for notation in ["V EH9", "", "V EH1\\nR", "V [EH1]"]:
            result = self.action("PATCH", suffix,
                                 self.english_payload("V EH1 R IY0", notation))
            self.assertEqual(result.status_code, 422)
        valid = self.action("PATCH", suffix,
                            self.english_payload("V EH1 R IY0", "V"))
        self.assertEqual(valid.status_code, 200, valid.text)
        # This separate conflict check observes updated server state, never modifies it.
        new_base = self.fake.query.model_dump()
        self.assertEqual(self.action(
            "PATCH", suffix, self.english_payload("V", "V AH1"),
            revision=original_rev,
        ).status_code, 409)
        self.assertEqual(self.action(
            "PATCH", suffix, self.english_payload("V EH1 R IY0", "V AH1")
        ).status_code, 422)
        self.assertEqual(self.action(
            "PATCH", suffix, self.english_payload("V", "V AH1"),
            headers=self.read,
        ).status_code, 403)
        self.assertEqual(self.fake.query.model_dump(), new_base)
        self.assertNotEqual(before, new_base)

    def test_english_only_and_grouping_mismatch_not_silent(self):
        self.fake._query = AudioQuery(
            accent_phrases=[], kana=None,
            voicegerSegments=[VoicegerSegment(language="en", text="very sweet!",
                phonemes=[p for _, tokens in GROUPS for p in tokens])]
        )
        item = self.batch()["items"][0]
        self.assertEqual([s["language"] for s in item["pronunciation_sections"]], ["en"])
        self.assertEqual(item["pronunciation_sections"][0]["groups"][0]["label"], "very")
        self.fake._query.voicegerSegments[0].phonemes = ["B", "AE1", "D"]
        broken = self.batch()["items"][0]["pronunciation_sections"][0]
        self.assertEqual(broken["error"], "grouping_unavailable")
        self.assertNotIn("groups", broken)
        self.assertEqual(self.action("PATCH", "/pronunciation/english/0/0",
            self.english_payload("V EH1 R IY0", "B AE1 D")).status_code, 422)
