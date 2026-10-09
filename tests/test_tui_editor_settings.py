import curses
from pathlib import Path
import unittest
from unittest.mock import patch

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editors import (
    AdjustmentPressedIntent,
    ApplySettingsIntent,
    ClearAdjustmentFeedbackIntent,
    CloseEditorIntent,
    TuiEditorController,
    UpdateStatusIntent,
)
from voiceger_editor.tui_rendering import _active_input_prefix
from voiceger_editor.tui_status import error_status
from voiceger_editor.tui_editor_settings import TuiSettingsEditorOwner
from tests.tui_editor_test_support import EditorControllerTestCase


class TuiSettingsEditorOwnerTests(EditorControllerTestCase):
    def make_owner_controller(self):
        return TuiEditorController(
            english_word_groups=lambda _text: (),
            available_styles=lambda: (),
            input_prefix=_active_input_prefix,
        )

    def test_settings_owner_holds_adjustment_policy_behind_facade(self):
        controller = self.make_owner_controller()
        self.assertIsInstance(controller._settings, TuiSettingsEditorOwner)
        controller.open_settings(
            Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            origin=("settings", None),
            busy=False,
        )
        controller.editor.selection = "top_k"
        before = controller.editor.payload["draft_settings"]["top_k"]

        controller.handle_key(
            curses.KEY_RIGHT,
            settings=Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            query=None,
            current_caption=None,
        )

        self.assertNotEqual(
            controller.editor.payload["draft_settings"]["top_k"],
            before,
        )

    def test_settings_keep_draft_apply_semantics_and_emit_movement_feedback(self):
        styles = (
            type("Style", (), {"id": 3, "name": "Neutral"})(),
            type("Style", (), {"id": 1, "name": "Sweet"})(),
            type("Style", (), {"id": 22, "name": "Whispering"})(),
        )
        controller, _provider = self.make_controller(styles=styles)
        controller.open_settings(
            self.settings(), origin=("settings", None), busy=False
        )
        self.assertEqual(controller.editor.selection, "style_id")
        self.assertEqual(controller.adjust_settings(-1), (ClearAdjustmentFeedbackIntent(),))
        self.assertEqual(controller.adjust_settings(1), (AdjustmentPressedIntent("settings", "style_id", 1),))
        self.assertEqual(controller.editor.payload["draft_settings"]["style_id"], "1")
        self.assertEqual(controller.adjust_settings(1), (AdjustmentPressedIntent("settings", "style_id", 1),))
        self.assertEqual(controller.editor.payload["draft_settings"]["style_id"], "22")
        self.assertEqual(controller.adjust_settings(-1), (AdjustmentPressedIntent("settings", "style_id", -1),))
        self.assertEqual(controller.editor.payload["draft_settings"]["style_id"], "1")
        controller.editor.selection = "apply"
        intent = controller._activate_selection(self.settings(), None, None)[0]
        self.assertIsInstance(intent, ApplySettingsIntent)
        self.assertEqual(intent.settings.style_id, 1)
        self.assertEqual(intent.settings.output_dir, self.settings().output_dir)

    def test_settings_reject_unavailable_style_id_instead_of_falling_back(self):
        styles = (
            type("Style", (), {"id": 3, "name": "Neutral"})(),
            type("Style", (), {"id": 1, "name": "Sweet"})(),
        )
        controller, _provider = self.make_controller(styles=styles)
        controller.open_settings(
            Settings(style_id=2), origin=("settings", None), busy=False
        )

        self.assertEqual(
            controller.adjust_settings(1),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(
            controller.editor.payload["draft_settings"]["style_id"],
            "2",
        )
        self.assertEqual(
            controller.editor.error,
            error_status("Style ID 2 is not available."),
        )

    def test_sampling_settings_adjust_edit_reset_and_apply_as_draft(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor

        editor.selection = "top_k"
        self.assertEqual(
            controller.adjust_settings(1),
            (AdjustmentPressedIntent("settings", "top_k", 1),),
        )
        self.assertEqual(editor.payload["draft_settings"]["top_k"], "21")
        editor.payload["draft_settings"]["top_k"] = "100"
        self.assertEqual(
            controller.adjust_settings(1),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(editor.payload["draft_settings"]["top_k"], "100")

        editor.selection = "top_p"
        self.assertEqual(
            controller.adjust_settings(-1),
            (AdjustmentPressedIntent("settings", "top_p", -1),),
        )
        self.assertEqual(editor.payload["draft_settings"]["top_p"], "0.95")

        editor.selection = "temperature"
        controller.adjust_settings(-1)
        self.assertEqual(editor.payload["draft_settings"]["temperature"], "0.95")
        self.assertEqual(settings.temperature, 1.0)

        for field, value, expected in (
            ("top_k", "37", "37"),
            ("top_p", "0.35", "0.35"),
            ("temperature", "0.65", "0.65"),
        ):
            with self.subTest(direct_edit=field):
                editor.selection = field
                controller.handle_key(
                    "\n", settings=settings, query=None, current_caption=None
                )
                self.assertEqual(editor.active_field, field)
                editor.input_value = value
                editor.input_cursor = len(editor.input_value)
                controller.handle_key(
                    "\n", settings=settings, query=None, current_caption=None
                )
                self.assertIsNone(editor.active_field)
                self.assertEqual(
                    editor.payload["draft_settings"][field],
                    expected,
                )

        editor.payload["draft_settings"]["take_count"] = "9"
        editor.selection = "reset_sampling"
        intents = controller.handle_key(
            "\n", settings=settings, query=None, current_caption=None
        )
        self.assertEqual(editor.payload["draft_settings"]["top_k"], "20")
        self.assertEqual(editor.payload["draft_settings"]["top_p"], "1.00")
        self.assertEqual(editor.payload["draft_settings"]["temperature"], "1.00")
        self.assertEqual(editor.payload["draft_settings"]["take_count"], "9")
        self.assertEqual(
            intents[-1],
            UpdateStatusIntent("Sampling reset to Voiceger defaults."),
        )

        editor.payload["draft_settings"]["top_k"] = "37"
        editor.payload["draft_settings"]["top_p"] = "0.45"
        editor.payload["draft_settings"]["temperature"] = "0.80"
        editor.selection = "apply"
        apply = controller.handle_key(
            "\n", settings=settings, query=None, current_caption=None
        )
        self.assertEqual(len(apply), 1)
        self.assertIsInstance(apply[0], ApplySettingsIntent)
        self.assertEqual(apply[0].settings.top_k, 37)
        self.assertEqual(apply[0].settings.top_p, 0.45)
        self.assertEqual(apply[0].settings.temperature, 0.80)

    def test_settings_selection_order_and_adjustable_enter_emit_full_targets(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        self.assertEqual(
            controller.selection_keys(),
            [
                "style_id", "speed", "take_count", "output_dir", "audio_output",
                "top_k", "top_p", "temperature", "reset_sampling",
                "apply", "reset", "back",
            ],
        )

        drafts = (
            ("style_id", {"style_id": "22"}, Settings(style_id=22, output_dir=settings.output_dir)),
            ("speed", {"speed": "1.25"}, Settings(speed=1.25, output_dir=settings.output_dir)),
        )
        for field, updates, expected in drafts:
            with self.subTest(field=field):
                controller.open_settings(
                    settings, origin=("settings", None), busy=False
                )
                editor = controller.editor
                editor.payload["draft_settings"].update(updates)
                editor.selection = field
                intents = controller.handle_key(
                    "\n", settings=settings, query=None, current_caption=None
                )
                self.assertEqual(intents, (ApplySettingsIntent(expected),))
                self.assertIs(controller.editor, editor)
                self.assertIsNone(editor.active_field)

    def test_audio_output_template_validation_and_back_preserve_parent_draft(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        parent = controller.editor
        parent.selection = "audio_output"

        controller.handle_key(
            "\n", settings=settings, query=None, current_caption="今日は雨"
        )
        editor = controller.editor
        self.assertEqual(editor.kind, "audio_output_settings")
        self.assertEqual(
            controller.selection_keys(),
            [
                "output_format", "output_encoding", "filename_template",
                "save_text", "save_lab", "back",
            ],
        )
        self.assertIs(editor.payload["draft_settings"], parent.payload["draft_settings"])

        editor.selection = "filename_template"
        controller.handle_key(
            "\n", settings=settings, query=None, current_caption="今日は雨"
        )
        editor.input_value = "{take}_{caption}"
        self.assertEqual(
            controller.handle_key(
                "\n", settings=settings, query=None, current_caption="今日は雨"
            ),
            (),
        )
        self.assertEqual(editor.active_field, "filename_template")
        self.assertIn("Filename template is invalid", str(editor.error))

        editor.input_value = "{YYYY-MM-DD}_{style}_{caption}"
        controller.handle_key(
            "\n", settings=settings, query=None, current_caption="今日は雨"
        )
        self.assertIsNone(editor.active_field)
        self.assertEqual(
            editor.payload["draft_settings"]["filename_template"],
            "{YYYY-MM-DD}_{style}_{caption}",
        )

        controller.handle_key(
            "\x1b", settings=settings, query=None, current_caption="今日は雨"
        )
        self.assertIs(controller.editor, parent)
        self.assertEqual(
            parent.payload["draft_settings"]["filename_template"],
            "{YYYY-MM-DD}_{style}_{caption}",
        )

    @patch(
        "voiceger_editor.tui_editors.available_output_formats",
        return_value=("wav", "flac"),
    )
    def test_audio_output_switching_preserves_format_specific_encoding_and_preview(
        self, _formats
    ):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        controller.editor.selection = "audio_output"
        controller.handle_key(
            "\n", settings=settings, query=None, current_caption="Preview caption"
        )
        editor = controller.editor
        draft = editor.payload["draft_settings"]

        self.assertEqual(editor.selection, "output_format")
        self.assertEqual(draft["output_format"], "wav")
        self.assertEqual(draft["wav_encoding"], "source")
        self.assertTrue(editor.payload["filename_preview"].endswith(".wav"))

        editor.selection = "output_encoding"
        controller.adjust_settings(1)
        self.assertEqual(draft["wav_encoding"], "pcm16")

        editor.selection = "output_format"
        controller.adjust_settings(1)
        self.assertEqual(draft["output_format"], "flac")
        self.assertEqual(draft["flac_encoding"], "pcm16")
        self.assertTrue(editor.payload["filename_preview"].endswith(".flac"))

        editor.selection = "output_encoding"
        controller.adjust_settings(1)
        self.assertEqual(draft["flac_encoding"], "pcm24")
        self.assertEqual(
            controller.adjust_settings(1),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(draft["flac_encoding"], "pcm24")

        editor.selection = "output_format"
        controller.adjust_settings(1)
        self.assertEqual(draft["output_format"], "wav")
        self.assertEqual(draft["wav_encoding"], "pcm16")
        editor.selection = "output_encoding"
        controller.adjust_settings(-1)
        self.assertEqual(draft["wav_encoding"], "source")
        self.assertEqual(
            controller.adjust_settings(-1),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(draft["wav_encoding"], "source")
        editor.selection = "output_format"
        controller.adjust_settings(1)
        self.assertEqual(draft["output_format"], "flac")
        self.assertEqual(draft["flac_encoding"], "pcm24")

    @patch(
        "voiceger_editor.tui_editors.available_output_formats",
        return_value=("wav", "flac", "mp3"),
    )
    def test_audio_output_mp3_uses_bitrate_row_and_remembers_bitrate(self, _formats):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        controller.editor.selection = "audio_output"
        controller.handle_key(
            "\n", settings=settings, query=None, current_caption="Preview caption"
        )
        editor = controller.editor
        draft = editor.payload["draft_settings"]

        editor.selection = "output_format"
        controller.adjust_settings(1)
        controller.adjust_settings(1)

        self.assertEqual(draft["output_format"], "mp3")
        self.assertEqual(
            controller.selection_keys(),
            [
                "output_format", "mp3_bitrate", "filename_template",
                "save_text", "save_lab", "back",
            ],
        )
        self.assertTrue(editor.payload["filename_preview"].endswith(".mp3"))
        editor.selection = "mp3_bitrate"
        controller.adjust_settings(1)
        self.assertEqual(draft["mp3_bitrate"], "256k")

        editor.selection = "output_format"
        controller.adjust_settings(1)
        self.assertEqual(draft["output_format"], "wav")
        controller.adjust_settings(-1)
        self.assertEqual(draft["output_format"], "mp3")
        self.assertEqual(draft["mp3_bitrate"], "256k")

    @patch(
        "voiceger_editor.tui_editors.available_output_formats",
        return_value=("wav", "flac"),
    )
    def test_audio_output_without_ffmpeg_never_selects_mp3(self, _formats):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        controller.editor.selection = "audio_output"
        controller.handle_key(
            "\n", settings=settings, query=None, current_caption="Preview caption"
        )
        editor = controller.editor

        editor.selection = "output_format"
        controller.adjust_settings(1)
        self.assertEqual(editor.payload["draft_settings"]["output_format"], "flac")
        controller.adjust_settings(1)
        self.assertEqual(editor.payload["draft_settings"]["output_format"], "wav")
        self.assertNotIn("mp3_bitrate", controller.selection_keys())

    def test_settings_txt_left_and_right_each_toggle_continuously(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        controller.editor.selection = "audio_output"
        controller.handle_key(
            "\n", settings=settings, query=None, current_caption="Preview caption"
        )
        editor = controller.editor
        self.assertEqual(editor.kind, "audio_output_settings")
        editor.selection = "save_text"
        editor.payload["draft_settings"]["save_text"] = False

        self.assertEqual(
            controller.adjust_settings(-1),
            (AdjustmentPressedIntent("settings", "save_text", -1),),
        )
        self.assertTrue(editor.payload["draft_settings"]["save_text"])
        self.assertEqual(
            controller.adjust_settings(-1),
            (AdjustmentPressedIntent("settings", "save_text", -1),),
        )
        self.assertFalse(editor.payload["draft_settings"]["save_text"])
        self.assertEqual(
            controller.adjust_settings(1),
            (AdjustmentPressedIntent("settings", "save_text", 1),),
        )
        self.assertTrue(editor.payload["draft_settings"]["save_text"])
        self.assertEqual(
            controller.adjust_settings(1),
            (AdjustmentPressedIntent("settings", "save_text", 1),),
        )
        self.assertFalse(editor.payload["draft_settings"]["save_text"])

    def test_settings_tab_and_backtab_move_between_section_starts_and_wrap(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor

        for expected in ("take_count", "output_dir", "top_k", "apply", "style_id"):
            intents = controller.handle_key(
                "\t", settings=settings, query=None, current_caption=None
            )
            self.assertEqual(intents, (ClearAdjustmentFeedbackIntent(),))
            self.assertEqual(editor.selection, expected)

        backtab = getattr(curses, "KEY_BTAB")
        for expected in ("apply", "top_k", "output_dir", "take_count", "style_id"):
            intents = controller.handle_key(
                backtab, settings=settings, query=None, current_caption=None
            )
            self.assertEqual(intents, (ClearAdjustmentFeedbackIntent(),))
            self.assertEqual(editor.selection, expected)

    def test_sampling_shortcuts_focus_rows_and_reset_only_the_draft(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor

        for shortcut, expected in (("k", "top_k"), ("p", "top_p"), ("t", "temperature")):
            with self.subTest(shortcut=shortcut):
                intents = controller.handle_key(
                    shortcut, settings=settings, query=None, current_caption=None
                )
                self.assertEqual(intents, (ClearAdjustmentFeedbackIntent(),))
                self.assertEqual(editor.selection, expected)

        editor.payload["draft_settings"].update(
            {"top_k": "37", "top_p": "0.45", "temperature": "0.80"}
        )
        intents = controller.handle_key(
            "d", settings=settings, query=None, current_caption=None
        )
        self.assertEqual(editor.selection, "reset_sampling")
        self.assertEqual(editor.payload["draft_settings"]["top_k"], "20")
        self.assertEqual(editor.payload["draft_settings"]["top_p"], "1.00")
        self.assertEqual(editor.payload["draft_settings"]["temperature"], "1.00")
        self.assertEqual(settings.top_k, 20)
        self.assertEqual(settings.top_p, 1.0)
        self.assertEqual(settings.temperature, 1.0)
        self.assertEqual(
            intents[-1],
            UpdateStatusIntent("Sampling reset to Voiceger defaults."),
        )

    def test_settings_take_count_enter_edits_numeric_draft_before_explicit_apply(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor
        editor.selection = "take_count"

        self.assertEqual(
            controller.handle_key(
                "\n", settings=settings, query=None, current_caption=None
            ),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(editor.active_field, "take_count")
        self.assertEqual(editor.input_value, "4")

        editor.input_value = "42"
        editor.input_cursor = 2
        self.assertEqual(
            controller.handle_key(
                "\n", settings=settings, query=None, current_caption=None
            ),
            (UpdateStatusIntent(""),),
        )
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.payload["draft_settings"]["take_count"], "42")
        self.assertIs(controller.editor, editor)

        editor.selection = "apply"
        self.assertEqual(
            controller.handle_key(
                "\n", settings=settings, query=None, current_caption=None
            ),
            (
                ApplySettingsIntent(
                    Settings(take_count=42, output_dir=settings.output_dir)
                ),
            ),
        )

    def test_settings_take_count_direct_edit_rejects_invalid_values_in_place(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor
        editor.selection = "take_count"
        controller.handle_key(
            "\n", settings=settings, query=None, current_caption=None
        )

        for value in ("101", "not-a-number"):
            with self.subTest(value=value):
                editor.input_value = value
                editor.input_cursor = len(value)
                self.assertEqual(
                    controller.handle_key(
                        "\n", settings=settings, query=None, current_caption=None
                    ),
                    (),
                )
                self.assertEqual(editor.active_field, "take_count")
                self.assertEqual(
                    editor.payload["draft_settings"]["take_count"],
                    "4",
                )
                self.assertIn(
                    "Take count must be an integer from 1 through 100",
                    editor.error,
                )

    def test_settings_validation_rejects_invalid_full_draft_before_emitting_apply(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor
        editor.payload["draft_settings"]["take_count"] = "101"

        intents = controller.handle_key(
            "\n", settings=settings, query=None, current_caption=None
        )

        self.assertEqual(intents, ())
        self.assertIs(controller.editor, editor)
        self.assertIn("take_count must be an integer from 1 through 100", editor.error)

    def test_settings_reset_restores_opening_snapshot_and_back_or_escape_discards(self):
        opening = Settings(
            style_id=3,
            speed=1.2,
            take_count=6,
            output_dir=Path("/tmp/opening-output"),
            save_text=True,
        )
        controller, _provider = self.make_controller()
        controller.open_settings(opening, origin=("help", None), busy=False)
        editor = controller.editor
        editor.payload["draft_settings"].update(
            {
                "style_id": "7",
                "speed": "2.00",
                "take_count": "1",
                "output_dir": "/tmp/changed-output",
                "save_text": False,
            }
        )
        editor.selection = "reset"
        intents = controller.handle_key(
            "\n", settings=opening, query=None, current_caption=None
        )
        self.assertEqual(
            editor.payload["draft_settings"],
            {
                "style_id": "3",
                "speed": "1.2",
                "take_count": "6",
                "output_dir": "/tmp/opening-output",
                "filename_template": "{YYYYMMDDHHmm}_{caption}",
                "output_format": "wav",
                "wav_encoding": "source",
                "flac_encoding": "pcm16",
                "mp3_bitrate": "192k",
                "save_text": True,
                "save_lab": False,
                "top_k": "20",
                "top_p": "1.00",
                "temperature": "1.00",
            },
        )
        self.assertEqual(intents[-1], UpdateStatusIntent("Settings draft reset."))
        self.assertIs(controller.editor, editor)

        editor.payload["draft_settings"]["take_count"] = "2"
        editor.selection = "back"
        back = controller.handle_key(
            "\n", settings=opening, query=None, current_caption=None
        )
        self.assertIsNone(controller.editor)
        self.assertEqual(
            back[-1], CloseEditorIntent(("help", None), "Settings draft discarded.")
        )

        controller.open_settings(opening, origin=("settings", None), busy=False)
        controller.editor.payload["draft_settings"]["style_id"] = "1"
        cancelled = controller.handle_key(
            "\x1b", settings=opening, query=None, current_caption=None
        )
        self.assertIsNone(controller.editor)
        self.assertEqual(
            cancelled[-1],
            CloseEditorIntent(("settings", None), "Settings draft discarded."),
        )

    def test_settings_field_edits_remain_on_the_same_selection_row(self):
        controller, _provider = self.make_controller()
        controller.open_settings(
            self.settings(), origin=("settings", None), busy=False,
            selected_field="output_dir",
        )
        self.assertEqual(controller.editor.selection, "output_dir")
        self.assertIsNone(controller.editor.active_field)
        controller.handle_key(
            "\n", settings=self.settings(), query=None, current_caption=None
        )
        self.assertEqual(controller.editor.active_field, "output_dir")
        controller.editor.input_value = "/tmp/new-output"
        self.assertEqual(
            controller.handle_key(
                "\n", settings=self.settings(), query=None, current_caption=None
            ),
            (UpdateStatusIntent(""),),
        )
        self.assertEqual(controller.editor.selection, "output_dir")
        self.assertIsNone(controller.editor.active_field)
        self.assertEqual(
            controller.editor.payload["draft_settings"]["output_dir"],
            "/tmp/new-output",
        )


if __name__ == "__main__":
    unittest.main()
