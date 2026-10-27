"""Direct per-item voice controls, preserved Takes and shared Settings behavior."""

from __future__ import annotations

import curses
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from voiceger_editor.caption_batch import CaptionBatchItem
from voiceger_editor.styles import VoicegerStyle
from tests.tui_app_test_support import (
    TuiAppTestCase, FakeScreen, FakeSession, candidate, mixed_query,
)

STYLES = (
    VoicegerStyle(3, "Neutral", "neutral.wav"),
    VoicegerStyle(1, "Sweet", "sweet.wav"),
    VoicegerStyle(7, "Snippy", "snippy.wav"),
)


class TuiItemVoiceTests(TuiAppTestCase):
    def make_three(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        sessions = [app.session]
        for number in (2, 3):
            session = FakeSession(query=mixed_query(), candidates=(candidate(1),))
            session.caption = f"Caption {number}"
            app._batch.batch.add_item(CaptionBatchItem(session))
            sessions.append(session)
        return app, sessions

    def test_item_style_loops_and_keeps_candidates_and_acceptance(self):
        app, sessions = self.make_three()
        first = app._batch.batch.items[0]
        app._batch.batch.mark_accepted(first.item_id, 1)
        with patch("voiceger_editor.tui.available_styles", return_value=STYLES):
            app._handle_key("s")
            self.assertEqual(app._navigation.focus_key, ("item_style", None))
            self.assertIsNone(app._editor_controller.editor)
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(sessions[0].settings.style_id, 1)
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(sessions[0].settings.style_id, 7)
            app._handle_key(curses.KEY_RIGHT)
            self.assertEqual(sessions[0].settings.style_id, 3)
            app._handle_key(curses.KEY_LEFT)
            self.assertEqual(sessions[0].settings.style_id, 7)
        self.assertEqual([s.settings.style_id for s in sessions], [7, 3, 3])
        self.assertEqual(len(sessions[0].candidates), 1)
        self.assertTrue(first.is_accepted)
        self.assertTrue(all(len(s.candidates) == 1 for s in sessions))

    def test_speed_steps_and_numeric_enter_edit_and_escape(self):
        app, sessions = self.make_three()
        app._handle_key("v")
        self.assertEqual(app._navigation.focus_key, ("item_speed", None))
        app._handle_key(curses.KEY_RIGHT)
        self.assertEqual(sessions[0].settings.speed, 1.01)
        app._handle_key("\n")
        self.assertIsNotNone(app._batch_item_controller.speed_edit)
        app._batch_item_controller.speed_edit.value = "0.85"
        app._handle_key("\n")
        self.assertIsNone(app._batch_item_controller.speed_edit)
        self.assertEqual(sessions[0].settings.speed, 0.85)
        self.assertEqual(sessions[1].settings.speed, 1.0)
        app._handle_key("\n")
        app._batch_item_controller.speed_edit.value = "2.50"
        app._handle_key("\x1b")
        self.assertIsNone(app._batch_item_controller.speed_edit)
        self.assertEqual(sessions[0].settings.speed, 0.85)
        self.assertEqual(len(sessions[0].candidates), 1)

    def test_invalid_speed_keeps_inline_edit_open(self):
        app = self.make_app(query=mixed_query())
        app._handle_key("v")
        app._handle_key("\n")
        app._batch_item_controller.speed_edit.value = "0"
        app._handle_key("\n")
        self.assertIsNotNone(app._batch_item_controller.speed_edit)
        self.assertIn("Speed must be", str(app._status))
        app._handle_key("\x1b")
        self.assertIsNone(app._batch_item_controller.speed_edit)

    def test_unrelated_global_settings_edits_preserve_local_voices(self):
        app, sessions = self.make_three()
        sessions[0].settings = replace(sessions[0].settings, style_id=1, speed=1.11)
        sessions[1].settings = replace(sessions[1].settings, style_id=7, speed=0.91)
        with patch("voiceger_editor.tui.save_settings"):
            app._change_settings(output_dir=Path("/tmp/item-voice-output"))
            self.assertEqual(
                [(s.settings.style_id, s.settings.speed) for s in sessions],
                [(1, 1.11), (7, 0.91), (3, 1.0)],
            )
            app._change_settings(speed=0.95)
            self.assertEqual([s.settings.speed for s in sessions], [0.95] * 3)
            app._change_settings(style_id=1)
            self.assertEqual([s.settings.style_id for s in sessions], [1] * 3)

    def test_generated_take_row_keeps_its_own_voice_snapshot(self):
        old_take = candidate(1)
        old_take.query = mixed_query()
        old_take.query.speedScale = 1.0
        old_take.style_name = "Neutral"
        app = self.make_app(query=mixed_query(), candidates=(old_take,))
        with patch("voiceger_editor.tui_rendering_navigation.available_styles", return_value=STYLES):
            app._screen = FakeScreen()
            app._render()
            initial = self.rendered(app._screen)
            self.assertIn("Take 1", initial)
            self.assertIn("Neutral | 1.00x | 0.01s", initial)
            app.session.settings = replace(app.session.settings, style_id=1, speed=1.10)
            app._screen.drawn.clear()
            app._render()
            rendered = self.rendered(app._screen)
        self.assertIn("Sweet", rendered)
        self.assertIn("1.10x", rendered)
        self.assertIn("Neutral | 1.00x | 0.01s", rendered)

    def test_item_style_and_speed_are_available_on_narrow_screen(self):
        app = self.make_app(query=mixed_query())
        with patch("voiceger_editor.tui_rendering_navigation.available_styles", return_value=STYLES):
            app._screen = FakeScreen(columns=32)
            app._render()
        rendered = self.rendered(app._screen)
        self.assertIn("[S] Style", rendered)
        self.assertIn("[V] Speed", rendered)
        self.assertNotIn("EDIT ITEM VOICE", rendered)

    def test_item_voice_is_blocked_during_preview(self):
        app = self.make_app(query=mixed_query())
        app._operations.busy = True
        app._operations.worker_operation = "preview"
        with patch("voiceger_editor.tui.available_styles", return_value=STYLES):
            app._handle_key("s")
            app._handle_key(curses.KEY_RIGHT)
        self.assertEqual(app.session.settings.style_id, 3)
        self.assertIn("Preview", str(app._status))
