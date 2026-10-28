"""Regression coverage for mobile Batch List core and protected HTTP adapters."""

from __future__ import annotations

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from voiceger_editor.web import create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


_TOKEN = "batch-editor-test-token-with-sufficient-entropy-0000"


class FakeSession:
    def __init__(self, caption):
        self.caption = caption
        self.is_prepared = False
        self.active_candidate_count = 0
        self.discards = 0

    def replace_caption(self, value):
        self.caption = value

    def discard_takes(self):
        self.discards += 1


class MobileBatchTests(unittest.TestCase):
    def setUp(self):
        self.sessions = []
        def factory(caption):
            instance = FakeSession(caption)
            self.sessions.append(instance)
            return instance

        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": _TOKEN})
        self.auth.start()
        self.service = WebSessionOperations(
            caption_factory=factory,
            runtime_checker=lambda: SimpleNamespace(ready=True),
        )
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + _TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        response = self.client.post("/api/web/sessions", headers=self.write)
        self.assertEqual(response.status_code, 201)
        self.sid = response.json()["id"]

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.auth.stop()

    @property
    def path(self):
        return "/api/web/sessions/" + self.sid + "/batch"

    def read_batch(self):
        response = self.client.get(self.path, headers=self.read)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def edit(self, method, subpath, body=None, *, revision=None, headers=None):
        rev = self.read_batch()["revision"] if revision is None else revision
        response = self.client.request(
            method, self.path + subpath + "?expected_revision=" + str(rev),
            headers=self.write if headers is None else headers,
            json=body,
        )
        return response

    def test_multiline_add_identity_inclusion_order_and_take_counts(self):
        added = self.edit("POST", "/items", {"text": "第一行\n\n第二行\n第三行"})
        self.assertEqual(added.status_code, 200, added.text)
        data = added.json()
        self.assertEqual(data["revision"], 1)
        self.assertEqual([i["caption"] for i in data["items"]], ["第一行", "第二行", "第三行"])
        ids = [i["id"] for i in data["items"]]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(i["included"] for i in data["items"]))
        self.assertEqual([i["effective_take_count"] for i in data["items"]], [4, 4, 4])

        moved = self.edit("PATCH", f"/items/{ids[2]}/position", {"index": 0})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual([i["id"] for i in moved.json()["items"]], [ids[2], ids[0], ids[1]])

        included = self.edit("PATCH", f"/items/{ids[0]}/included", {"included": False})
        self.assertEqual(included.status_code, 200)
        self.assertFalse(next(i for i in included.json()["items"] if i["id"] == ids[0])["included"])

        self.assertEqual(self.edit("PATCH", "/default-take-count", {"count": 5}).status_code, 200)
        per_item = self.edit("PATCH", f"/items/{ids[0]}/take-count", {"count": 2})
        self.assertEqual(per_item.status_code, 200)
        self.assertEqual(next(i for i in per_item.json()["items"] if i["id"] == ids[0])["effective_take_count"], 2)
        self.assertEqual(self.edit("PATCH", f"/items/{ids[0]}/take-count", {"count": None}).status_code, 200)
        self.assertEqual(next(i for i in self.read_batch()["items"] if i["id"] == ids[0])["effective_take_count"], 5)

    def test_caption_only_edit_does_not_invalidate_takes_and_delete_cleans(self):
        added = self.edit("POST", "/items", {"text": "声と別の字幕"})
        item_id = added.json()["items"][0]["id"]
        original = self.sessions[0]
        original.is_prepared = True
        original.active_candidate_count = 3
        changed = self.edit("PATCH", f"/items/{item_id}/caption", {"caption": "字幕だけ変更"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["items"][0]["caption"], "字幕だけ変更")
        self.assertEqual(changed.json()["items"][0]["candidate_count"], 3)
        self.assertEqual(original.discards, 0)

        self.assertEqual(self.edit("DELETE", f"/items/{item_id}").status_code, 200)
        self.assertEqual(original.discards, 1)
        self.assertEqual(self.read_batch()["items"], [])

    def test_atomic_invalid_paste_limits_and_stale_revision(self):
        initial = self.edit("POST", "/items", {"text": "保存済み"})
        self.assertEqual(initial.status_code, 200)
        before = self.read_batch()
        invalid = self.edit("POST", "/items", {"text": "有効\n" + "a" * 2001})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.read_batch(), before)

        for body, route in [
            ({"count": 0}, "/default-take-count"),
            ({"count": 101}, "/default-take-count"),
            ({"count": True}, "/default-take-count"),
        ]:
            self.assertEqual(self.edit("PATCH", route, body).status_code, 422)
        item_id = before["items"][0]["id"]
        self.assertEqual(self.edit("PATCH", f"/items/{item_id}/position", {"index": 100}).status_code, 422)
        self.assertEqual(self.edit("PATCH", f"/items/{item_id}/included", {"included": "false"}).status_code, 422)
        self.assertEqual(self.read_batch(), before)

        stale = self.edit("POST", "/items", {"text": "遅れたリクエスト"}, revision=0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.read_batch(), before)

    def test_cross_session_isolation_and_missing_ids(self):
        other = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        self.assertEqual(self.edit("POST", "/items", {"text": "セッションA"}).status_code, 200)
        other_list = self.client.get(f"/api/web/sessions/{other}/batch", headers=self.read).json()
        self.assertEqual(other_list["items"], [])
        self.assertEqual(self.edit("DELETE", "/items/nonexistent").status_code, 404)
        self.assertEqual(self.client.get(self.path + "/nonexistent", headers=self.read).status_code, 404)

    def test_authorization_origin_csrf_and_invalid_input(self):
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertEqual(self.client.get(self.path, headers={"Authorization": "Bearer wrong"}).status_code, 401)
        self.assertEqual(self.edit("POST", "/items", {"text": "test"}, headers=self.read).status_code, 403)
        bad_origin = {**self.write, "Origin": "https://other.example"}
        self.assertEqual(self.edit("POST", "/items", {"text": "test"}, headers=bad_origin).status_code, 403)
        with patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": ""}):
            self.assertEqual(self.client.get(self.path, headers=self.read).status_code, 503)
        self.assertEqual(self.read_batch()["items"], [])

    def test_worker_blocks_mutations(self):
        started = threading.Event()
        release = threading.Event()
        def checker():
            started.set()
            release.wait(2)
            return SimpleNamespace(ready=True)
        self.service._runtime_checker = checker
        try:
            response = self.client.post(
                f"/api/web/sessions/{self.sid}/operations/runtime-check",
                headers=self.write,
            )
            self.assertEqual(response.status_code, 202)
            self.assertTrue(started.wait(1))
            self.assertEqual(self.edit("POST", "/items", {"text": "blocked"}).status_code, 409)
            self.assertEqual(self.read_batch()["items"], [])
        finally:
            release.set()

    def test_mobile_page_has_token_form_without_exposing_server_secret(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="auth-form"', response.text)
        self.assertIn('id="caption-list"', response.text)
        self.assertIn('id="view-item"', response.text)
        self.assertIn('id="view-list"', response.text)
        self.assertIn('id="view-add"', response.text)
        self.assertIn('id="view-session"', response.text)
        self.assertIn('id="item-back"', response.text)
        self.assertIn('type="password"', response.text)
        self.assertNotIn(_TOKEN, response.text)
        js = self.client.get("/assets/app.js").text
        self.assertIn('window.sessionStorage.setItem(SESSION_KEY, id)', js)
        self.assertNotIn('sessionStorage.setItem(SESSION_KEY, token)', js)
        self.assertNotIn("localStorage", js)
        self.assertIn("textContent = item.caption", js)
        self.assertNotIn("innerHTML", js)
        self.assertIn('function showView(name, bypassDraftGuard)', js)
        self.assertIn('function guardDraft()', js)
        self.assertIn('showView("list", true)', js)
        self.assertIn('caption.textContent = item.caption', js)
        self.assertNotIn('control("削除"', js)
        self.assertNotIn('control("編集"', js)
        self.assertIn('id="open-add"', response.text)
        self.assertIn('id="previous-item"', response.text)
        self.assertIn('id="next-item"', response.text)
        self.assertIn('id="move-up"', response.text)
        self.assertIn('id="move-down"', response.text)

    def test_mobile_screen_navigation_is_separate_from_list_controls(self):
        from html.parser import HTMLParser

        class Structure(HTMLParser):
            def __init__(self):
                super().__init__()
                self.screens = {}
                self.current_screen = None
                self.stack = []

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == "section" and attributes.get("id", "").startswith("view-"):
                    self.current_screen = attributes["id"]
                    self.screens[self.current_screen] = []
                self.stack.append((tag, attributes.get("id")))
                if self.current_screen and attributes.get("id"):
                    self.screens[self.current_screen].append(attributes["id"])

            def handle_endtag(self, tag):
                if self.stack:
                    opening_tag, identity = self.stack.pop()
                    if opening_tag == "section" and identity == self.current_screen:
                        self.current_screen = None

        parser = Structure()
        parser.feed(self.client.get("/").text)
        self.assertIn("caption-list", parser.screens["view-list"])
        self.assertIn("open-add", parser.screens["view-list"])
        self.assertNotIn("edit-caption", parser.screens["view-list"])
        self.assertNotIn("default-takes", parser.screens["view-list"])
        self.assertIn("edit-caption", parser.screens["view-item"])
        self.assertIn("item-included", parser.screens["view-item"])
        self.assertIn("new-captions", parser.screens["view-add"])
        self.assertIn("default-takes", parser.screens["view-session"])
        self.assertNotIn("web-token", parser.screens["view-list"])
        self.assertIn("web-token", parser.screens["view-connect"])



if __name__ == "__main__":
    unittest.main()
