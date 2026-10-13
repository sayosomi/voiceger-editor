"""Per-item voice draft, apply, retention, and global settings regression tests."""

from __future__ import annotations

import curses
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from voiceger_editor.caption_batch import CaptionBatchItem
from voiceger_editor.styles import VoicegerStyle
from tests.tui_app_test_support import (
    TuiAppTestCase,
    FakeScreen,
    FakeSession,
    candidate,
    mixed_query,
    set_navigation_focus,
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

    def open_voice(self, app):
        set_navigation_focus(app, ("settings_summary", None))
        app._handle_key("\n")
        self.assertEqual(app._editor_controller.editor.kind, "item_voice")

    def test_item_edits_are_scoped_and_cancel_preserves_takes(self):
        app, sessions = self.make_three()
        item_ids = [item.item_id for item in app._batch.batch.items]
        for item_id in item_ids:
            app._batch.batch.mark_accepted(item_id, 1)

        with patch("voiceger_editor.tui.available_styles", return_value=STYLES):
            self.open_voice(app)
            app._handle_key(curses.KEY_RIGHT)
            app._handle_key("\x1b")
            self.assertEqual(sessions[0].settings.style_id, 3)
            self.assertEqual(sessions[0].candidates, (candidate(1),))
            self.assertTrue(app._batch.batch.items[0].is_accepted)

            self.open_voice(app)
            app._handle_key("a")
            self.assertTrue(app._batch.batch.items[0].is_accepted)
            self.assertEqual(sessions[0].candidates, (candidate(1),))

            self.open_voice(app)
            app._handle_key(curses.KEY_RIGHT)
            app._handle_key(curses.KEY_DOWN)
            app._handle_key(curses.KEY_RIGHT)
            app._handle_key("a")
            self.assertEqual(sessions[0].settings.style_id, 1)
            self.assertEqual(sessions[0].settings.speed, 1.01)
            self.assertEqual(sessions[0].candidates, ())
            self.assertFalse(app._batch.batch.items[0].is_accepted)
            self.assertTrue(all(item.is_accepted for item in app._batch.batch.items[1:]))
            self.assertEqual([s.settings.style_id for s in sessions], [1, 3, 3])

            app.session = app._batch.open_item(1)
            self.open_voice(app)
            app._handle_key(curses.KEY_DOWN)
            app._handle_key("\n")
            editor = app._editor_controller.editor
            editor.input_value = "0.85"
            app._handle_key("\n")
            app._handle_key("a")
            self.assertEqual([s.settings.speed for s in sessions], [1.01, 0.85, 1.0])
            self.assertEqual([s.settings.style_id for s in sessions], [1, 3, 3])

    def test_reset_to_global_draft_then_apply_and_shortcuts(self):
        app, sessions = self.make_three()
        sessions[0].settings = replace(sessions[0].settings, style_id=7, speed=1.25)
        with patch("voiceger_editor.tui.available_styles", return_value=STYLES):
            self.open_voice(app)
            app._handle_key("r")
            draft = app._editor_controller.editor.payload
            self.assertEqual((draft["style_id"], draft["speed"]), ("3", "1.00"))
            self.assertEqual(sessions[0].settings.speed, 1.25)
            app._handle_key("a")
        self.assertEqual((sessions[0].settings.style_id, sessions[0].settings.speed), (3, 1.0))
        self.assertEqual(sessions[1].settings.speed, 1.0)

    def test_unrelated_global_settings_edits_preserve_item_voices(self):
        app, sessions = self.make_three()
        sessions[0].settings = replace(sessions[0].settings, style_id=1, speed=1.11)
        sessions[1].settings = replace(sessions[1].settings, style_id=7, speed=0.91)
        with patch("voiceger_editor.tui.save_settings"):
            app._change_settings(output_dir=Path("/tmp/item-voice-output"))
            self.assertEqual(
                [(s.settings.style_id, s.settings.speed) for s in sessions],
                [(1, 1.11), (7, 0.91), (3, 1.0)],
            )
            app._change_settings(style_id=3, speed=0.95)
            self.assertEqual(
                [(s.settings.style_id, s.settings.speed) for s in sessions],
                [(3, 0.95)] * 3,
            )

    def test_item_summary_uses_scoped_voice_not_global(self):
        app, sessions = self.make_three()
        sessions[0].settings = replace(sessions[0].settings, style_id=1, speed=1.12)
        app._screen = FakeScreen()
        with patch("voiceger_editor.tui_rendering.available_styles", return_value=STYLES):
            app._render()
        rendered = self.rendered(app._screen)
        self.assertIn("Sweet | 1.12x", rendered)
        self.assertIn("TXT OFF | LAB OFF", rendered)

    def test_item_voice_actions_remain_available_on_narrow_screen(self):
        app = self.make_app(query=mixed_query())
        with patch("voiceger_editor.tui.available_styles", return_value=STYLES):
            self.open_voice(app)
            app._screen = FakeScreen(columns=32)
            app._render()
        rendered = self.rendered(app._screen)
        self.assertIn("[A] Apply", rendered)
        self.assertIn("[R] Reset to Settings", rendered)
        self.assertIn("[Esc] Back", rendered)
