"""Issue #317: Web recipe transactions and Mac Output sandbox regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from voiceger_editor.caption_batch import CaptionBatch, CaptionBatchItem
from voiceger_editor.batch_recipe import BatchRecipeError, read_batch_recipe
from voiceger_editor import web_recipe
from voiceger_editor.settings import Settings
from voiceger_editor.web import ASSETS, create_web_app
from voiceger_editor.web_sessions import WebSessionOperations
from tests.test_web_batch import FakeSession


TOKEN = "recipe-web-test-token-with-sufficient-entropy-317"


class WebRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp.name)
        self.output = self.root_dir / "output"
        self.output.mkdir()
        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.settings = patch(
            "voiceger_editor.web_recipe.load_settings",
            return_value=Settings(output_dir=self.output),
        )
        self.auth.start()
        self.settings.start()
        self.service = WebSessionOperations(caption_factory=FakeSession)
        # These tests do not load the real Voiceger runtime or models.
        self.service._batch_adapter = object()
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        self.sid = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        self.base = "/api/web/sessions/" + self.sid + "/batch"

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.settings.stop()
        self.auth.stop()
        self.temp.cleanup()

    def batch(self):
        response = self.client.get(self.base, headers=self.read)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def call(self, suffix, payload=None, *, revision=None, headers=None):
        if revision is None:
            revision = self.batch()["revision"]
        return self.client.post(
            self.base + "/recipes" + suffix + "?expected_revision=" + str(revision),
            json=payload,
            headers=self.write if headers is None else headers,
        )

    def add(self, value="hello"):
        response = self.client.post(
            self.base + "/items?expected_revision=" + str(self.batch()["revision"]),
            headers=self.write, json={"text": value},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return self.service._sessions[self.sid].batch.items[-1]

    def test_empty_folder_and_filename_sandbox(self):
        response = self.client.get(self.base + "/recipes", headers=self.read)
        self.assertEqual(response.json(), {"files": [], "scope": "Mac Output folder"})
        (self.output / "one.voiceger.json").write_text("{}", encoding="utf-8")
        (self.output / "other.json").write_text("{}")
        (self.output / ".hidden.voiceger.json").write_text("{}")
        (self.output / "no.voiceger.json").mkdir()
        (self.root_dir / "secret.voiceger.json").write_text("secret")
        (self.output / "link.voiceger.json").symlink_to(
            self.root_dir / "secret.voiceger.json"
        )
        listing = self.client.get(self.base + "/recipes", headers=self.read).json()
        self.assertEqual(listing["files"], ["one.voiceger.json"])
        for bad in (
            "../secret.voiceger.json", "/tmp/x.voiceger.json", "a\\b.voiceger.json",
            "bad..voiceger.json", "bad.json", "\x00.voiceger.json",
            "C:\\secret.voiceger.json", ".hidden.voiceger.json",
        ):
            response = self.call("/read/review", {"filename": bad})
            self.assertEqual(response.status_code, 422, bad)
            self.assertEqual(response.json()["detail"]["code"], "invalid_filename")
        self.assertEqual(
            self.call("/read/review", {"filename": "link.voiceger.json"}).status_code,
            503,
        )
        self.assertEqual(
            self.call("/read/review", {"filename": "no.voiceger.json"}).status_code,
            503,
        )

    def test_save_preparation_checks_excluded_and_overwrite_confirmation(self):
        item = self.add()
        item.included_for_generation = False
        incomplete = self.call("/save/review", {"filename": "batch.voiceger.json"})
        self.assertEqual(incomplete.status_code, 422)
        self.assertEqual(incomplete.json()["detail"],
                         {"code": "missing_preparation", "item_index": 1})
        self.assertEqual(list(self.output.iterdir()), [])
        item.session.is_prepared = True

        def writer(path, batch):
            Path(path).write_text("new recipe", encoding="utf-8")
            return Path(path)

        target = self.output / "batch.voiceger.json"
        target.write_text("old recipe", encoding="utf-8")
        with patch("voiceger_editor.web_recipe.serialize_batch_recipe", return_value="{}"), \
             patch("voiceger_editor.web_recipe.write_batch_recipe", side_effect=writer):
            review = self.call("/save/review", {"filename": target.name})
            self.assertEqual(review.status_code, 200, review.text)
            self.assertTrue(review.json()["exists"])
            denied = self.call("/save/commit", {
                "token": review.json()["token"], "confirmed_overwrite": False,
            })
            self.assertEqual(denied.status_code, 409)
            self.assertEqual(target.read_text(), "old recipe")
            self.assertEqual(self.call("/save/commit", {
                "token": review.json()["token"], "confirmed_overwrite": True,
            }).status_code, 200)
            self.assertEqual(target.read_text(), "new recipe")
            self.assertIn(target.name, self.client.get(
                self.base + "/recipes", headers=self.read,
            ).json()["files"])
            no_overwrite = self.call("/save/review", {"filename": "new.voiceger.json"})
            self.assertFalse(no_overwrite.json()["exists"])
            (self.output / "new.voiceger.json").write_text("raced")
            raced = self.call("/save/commit", {
                "token": no_overwrite.json()["token"], "confirmed_overwrite": False,
            })
            self.assertEqual(raced.status_code, 409)
            self.assertEqual((self.output / "new.voiceger.json").read_text(), "raced")

    def test_read_requires_confirmed_snapshot_and_preserves_outputs(self):
        old = self.add("old caption")
        old.session.active_candidate_count = 2
        saved_audio = self.output / "accepted.wav"
        saved_audio.write_bytes(b"saved audio")
        recipe = self.output / "original.voiceger.json"
        recipe.write_text('{"a":1}', encoding="utf-8")
        fresh_session = FakeSession("new caption")
        fresh_session.is_prepared = True
        staged = CaptionBatch(default_take_count=5, items=[
            CaptionBatchItem(fresh_session),
        ])
        with patch("voiceger_editor.web_recipe.read_batch_recipe", return_value=staged):
            preview = self.call("/read/review", {"filename": recipe.name})
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertTrue(preview.json()["replace_required"])
            self.assertEqual(self.batch()["items"][0]["caption"], "old caption")
            self.assertEqual(old.session.discards, 0)
            self.assertEqual(self.call("/read/commit", {
                "token": preview.json()["token"], "confirmed_replace": True,
            }).status_code, 200)
        self.assertEqual(self.batch()["items"][0]["caption"], "new caption")
        self.assertEqual(self.batch()["default_take_count"], 5)
        self.assertEqual(self.batch()["revision"], 2)
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 0)
        self.assertEqual(old.session.discards, 1)
        self.assertEqual(saved_audio.read_bytes(), b"saved audio")

    def test_cancel_stale_file_invalid_recipe_and_concurrent_edit(self):
        old = self.add("old")
        recipe = self.output / "data.voiceger.json"
        recipe.write_text("not json", encoding="utf-8")
        broken = self.call("/read/review", {"filename": recipe.name})
        self.assertEqual(broken.status_code, 422)
        self.assertEqual(broken.json()["detail"]["code"], "invalid_recipe")
        self.assertEqual(self.batch()["items"][0]["caption"], "old")

        staged_sessions = []
        def reader(*args, **kwargs):
            session = FakeSession("loaded")
            staged_sessions.append(session)
            return CaptionBatch(
                default_take_count=4,
                items=[CaptionBatchItem(session)],
            )

        with patch("voiceger_editor.web_recipe.read_batch_recipe", side_effect=reader):
            p1 = self.call("/read/review", {"filename": recipe.name})
            self.assertEqual(p1.status_code, 200)
            self.assertEqual(self.call("/cancel").status_code, 200)
            self.assertEqual(staged_sessions[0].discards, 1)
            self.assertEqual(self.call("/read/commit", {
                "token": p1.json()["token"], "confirmed_replace": True,
            }).status_code, 409)
            p2 = self.call("/read/review", {"filename": recipe.name})
            recipe.write_text("changed", encoding="utf-8")
            change = self.call("/read/commit", {
                "token": p2.json()["token"], "confirmed_replace": True,
            })
            self.assertEqual(change.status_code, 409)
            self.assertEqual(change.json()["detail"]["code"], "recipe_changed")
            self.assertEqual(staged_sessions[-1].discards, 1)
            self.assertEqual(self.batch()["items"][0]["caption"], "old")
            p3 = self.call("/read/review", {"filename": recipe.name})
            self.add("another")
            self.assertEqual(self.call("/read/commit", {
                "token": p3.json()["token"], "confirmed_replace": True,
            }, revision=p3.json().get("revision", 1)).status_code, 409)
            self.assertEqual(self.batch()["items"][-1]["caption"], "another")

    def test_authorization_origin_worker_and_read_only_list(self):
        self.assertEqual(
            self.client.get(self.base + "/recipes").status_code, 401,
        )
        self.assertEqual(
            self.call("/save/review", {"filename": "batch.voiceger.json"},
                      headers=self.read).status_code, 403,
        )
        hostile = {**self.write, "Origin": "https://attacker.invalid"}
        self.assertEqual(
            self.call("/read/review", {"filename": "batch.voiceger.json"},
                      headers=hostile).status_code, 403,
        )
        self.service._active = (self.sid, "other-operation")
        try:
            result = self.call("/save/review", {"filename": "batch.voiceger.json"})
            self.assertEqual(result.status_code, 409)
            self.assertEqual(result.json()["detail"]["code"], "worker_busy")
        finally:
            self.service._active = None

    def test_overwrite_race_never_replaces_unreviewed_file(self):
        item = self.add()
        item.session.is_prepared = True
        target = self.output / "race.voiceger.json"
        target.write_text("approved old", encoding="utf-8")
        def writer(path, batch):
            Path(path).write_text("approved new", encoding="utf-8")
            return Path(path)
        original_rename = os.rename
        changed = []
        def concurrent_rename(src, dst, **kwargs):
            if src == target.name and not changed:
                # Another Mac process replaces the file after final fingerprint.
                other = self.output / "external.tmp"
                other.write_text("unreviewed external", encoding="utf-8")
                os.replace(other, target)
                changed.append(True)
            return original_rename(src, dst, **kwargs)
        with patch("voiceger_editor.web_recipe.serialize_batch_recipe", return_value="{}"), \
             patch("voiceger_editor.web_recipe.write_batch_recipe", side_effect=writer):
            p = self.call("/save/review", {"filename": target.name})
            self.assertEqual(p.status_code, 200)
            with patch("voiceger_editor.web_recipe.os.rename", side_effect=concurrent_rename):
                result = self.call("/save/commit", {
                    "token": p.json()["token"], "confirmed_overwrite": True,
                })
        self.assertEqual(result.status_code, 409, result.text)
        self.assertTrue(changed)
        self.assertEqual(target.read_text(encoding="utf-8"), "unreviewed external")
        self.assertFalse(list(self.output.glob(".voiceger-backup-*")))

    def test_overwrite_create_collision_preserves_both_files(self):
        item = self.add()
        item.session.is_prepared = True
        target = self.output / "collision.voiceger.json"
        target.write_text("verified old", encoding="utf-8")
        actual_link = os.link
        injected = []
        def concurrent_link(src, dst, **kwargs):
            if dst == target.name and not injected:
                # Another process creates a new target during the exclusive publish.
                target.write_text("new external", encoding="utf-8")
                injected.append(True)
            return actual_link(src, dst, **kwargs)
        def writer(path, batch):
            Path(path).write_text("new recipe", encoding="utf-8")
        with patch("voiceger_editor.web_recipe.serialize_batch_recipe", return_value="{}"), \
             patch("voiceger_editor.web_recipe.write_batch_recipe", side_effect=writer):
            p = self.call("/save/review", {"filename": target.name})
            with patch("voiceger_editor.web_recipe.os.link", side_effect=concurrent_link):
                result = self.call("/save/commit", {
                    "token": p.json()["token"], "confirmed_overwrite": True,
                })
        self.assertEqual(result.status_code, 409, result.text)
        self.assertTrue(injected)
        self.assertEqual(target.read_text(), "new external")
        backups = list(self.output.glob(".voiceger-backup-*.tmp"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "verified old")

    def test_read_same_bytes_different_inode_rejects(self):
        old = self.add("current")
        source = self.output / "identity.voiceger.json"
        source.write_bytes(b'{"same":"bytes"}')
        def reader(*args, **kwargs):
            return CaptionBatch(items=[CaptionBatchItem(FakeSession("staged"))])
        with patch("voiceger_editor.web_recipe.read_batch_recipe", side_effect=reader):
            p = self.call("/read/review", {"filename": source.name})
            self.assertEqual(p.status_code, 200)
            replacement = self.output / "copy.tmp"
            replacement.write_bytes(source.read_bytes())
            os.replace(replacement, source)
            outcome = self.call("/read/commit", {
                "token": p.json()["token"], "confirmed_replace": True,
            })
        self.assertEqual(outcome.status_code, 409)
        self.assertEqual(outcome.json()["detail"]["code"], "recipe_changed")
        self.assertEqual(self.batch()["items"][0]["caption"], "current")
        self.assertEqual(old.session.discards, 0)

    def test_output_directory_swap_cannot_escape(self):
        item = self.add()
        item.session.is_prepared = True
        target = "stay.voiceger.json"
        outside = self.root_dir / "outside"
        outside.mkdir()
        moved = self.root_dir / "former-output"
        original_stage = web_recipe._stage_recipe_file
        swapped = []
        def switch_output(fd, batch):
            name = original_stage(fd, batch)
            self.output.rename(moved)
            self.output.symlink_to(outside, target_is_directory=True)
            swapped.append(True)
            return name
        def writer(path, batch):
            Path(path).write_text("core", encoding="utf-8")
        with patch("voiceger_editor.web_recipe.serialize_batch_recipe", return_value="{}"), \
             patch("voiceger_editor.web_recipe.write_batch_recipe", side_effect=writer):
            p = self.call("/save/review", {"filename": target})
            self.assertEqual(p.status_code, 200)
            with patch("voiceger_editor.web_recipe._stage_recipe_file", side_effect=switch_output):
                result = self.call("/save/commit", {
                    "token": p.json()["token"], "confirmed_overwrite": False,
                })
        self.assertTrue(swapped)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["detail"]["code"], "recipe_changed")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((moved / target).exists())

    def test_web_max_items_rejected_before_session_construction(self):
        with patch("voiceger_editor.batch_recipe._load_document",
                   return_value=SimpleNamespace(items=[object()] * 201)), \
             patch("voiceger_editor.batch_recipe._resolve_style") as styles, \
             patch("voiceger_editor.batch_recipe.UtteranceSession") as sessions:
            with self.assertRaises(BatchRecipeError):
                read_batch_recipe(
                    self.output / "never-used.voiceger.json",
                    adapter=object(),
                    runtime_settings=Settings(output_dir=self.output),
                    max_items=200,
                )
            styles.assert_not_called()
            sessions.assert_not_called()

    def test_mobile_ui_has_compact_menu_and_warnings(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        for marker in (
            'id="open-batch-menu"', "Batch操作", "Macから読み込む",
            "Batchを保存", 'id="recipe-filename"', 'id="recipe-files"',
            'value="batch.voiceger.json"',
        ):
            self.assertIn(marker, html)
        self.assertIn("保存済みの音声ファイルは削除されません", js)
        self.assertIn("生成済みTake・採用状態", js)


if __name__ == "__main__":
    unittest.main()
