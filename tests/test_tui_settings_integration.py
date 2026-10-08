import curses
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from voiceger_editor.caption_batch import CaptionBatchItem
from voiceger_editor.openjtalk_dictionary import expand_word_type, normalize_surface
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.settings import Settings
from voiceger_editor.terms_acceptance import (
    ACCEPTANCE_COMMAND,
    OFFICIAL_TERMS_URL,
    TermsAcceptanceStatus,
    VoicegerTermsAcceptanceError,
)
from voiceger_editor.tui_editors import (
    OpenDictionaryIntent,
    PreviewIntent,
    ReplaceQueryIntent,
)
from voiceger_editor.tui_input import PasteText
from voiceger_editor.tui_operations import (
    BatchCandidateReplacedEffect,
    CandidateReplacedEffect,
    DiscardInitialBatchEffect,
    PlayPreviewEffect,
)
from voiceger_editor.tui_status import EMPTY_STATUS, StatusKind, error_status, info_status, warning_status
from voiceger_editor.tui import TuiApp, main
from voiceger_editor.user_dictionary import JapaneseWordType
from voiceger_editor.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


from tests.tui_app_test_support import (
    TuiAppTestCase,
    FakeScreen,
    candidate,
    editor_document,
    english_grouping,
    english_query,
    focus_candidate,
    japanese_query,
    mixed_query,
    navigation_document,
    navigation_items,
    set_navigation_focus,
)

class TuiSettingsIntegrationTests(TuiAppTestCase):
    def test_settings_are_reachable_and_editable_without_shortcuts(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query())
            app.config_path = Path(directory) / "config.json"
            for _ in range(len(navigation_items(app))):
                if app._navigation.focus_key == ("settings", None):
                    break
                app._handle_key(curses.KEY_DOWN)
            self.assertEqual(app._navigation.focus_key, ("settings", None))
            app._handle_key("\n")
            self.assertEqual(app._editor_controller.editor.kind, "settings")
            editor = app._editor_controller.editor
            editor.selection = "output_dir"
            app._handle_key("\n")
            self.assertEqual(editor.active_field, "output_dir")
            editor.input_value = "/tmp/settings-output"
            app._handle_key("\n")
            self.assertIsNotNone(editor)
            self.assertIsNone(editor.active_field)
            self.assertEqual(
                editor.payload["draft_settings"]["output_dir"],
                "/tmp/settings-output",
            )
            self.assertEqual(app.settings.output_dir, Settings().output_dir)
            self.assertEqual(app.session.replace_settings_calls, [])
            self.assertFalse(app.config_path.exists())
            editor.selection = "apply"
            app._handle_key("\n")
            self.assertIsNone(app._editor_controller.editor)
            self.assertEqual(app.settings.output_dir, Path("/tmp/settings-output"))
            self.assertEqual(
                json.loads(app.config_path.read_text())["output_dir"],
                "/tmp/settings-output",
            )

    def test_audio_output_template_and_sidecars_apply_with_parent_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "config.json"
            app._open_settings_editor()
            parent = app._editor_controller.editor
            parent.selection = "audio_output"
            app._handle_key("\n")
            editor = app._editor_controller.editor
            self.assertEqual(editor.kind, "audio_output_settings")

            editor.selection = "filename_template"
            app._handle_key("\n")
            editor.input_value = "{style}_{text}_{HHmmss}"
            app._handle_key("\n")
            editor.selection = "save_text"
            app._handle_key(curses.KEY_RIGHT)
            editor.selection = "save_lab"
            app._handle_key(curses.KEY_RIGHT)

            app._handle_key("\x1b")
            self.assertIs(app._editor_controller.editor, parent)
            parent.selection = "apply"
            app._handle_key("\n")

            self.assertIsNone(app._editor_controller.editor)
            self.assertEqual(app.settings.filename_template, "{style}_{text}_{HHmmss}")
            self.assertTrue(app.settings.save_text)
            self.assertTrue(app.settings.save_lab)
            saved = json.loads(app.config_path.read_text())
            self.assertEqual(saved["filename_template"], "{style}_{text}_{HHmmss}")
            self.assertTrue(saved["save_text"])
            self.assertTrue(saved["save_lab"])

    def test_sampling_draft_only_applies_and_invalidates_candidates_on_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
            app.config_path = Path(directory) / "config.json"
            app._operations.current_take = 1
            app._operations.stop_playback = Mock()
            app._open_settings_editor()
            editor = app._editor_controller.editor
            editor.selection = "top_p"

            app._handle_key(curses.KEY_LEFT)

            self.assertEqual(editor.payload["draft_settings"]["top_p"], "0.95")
            self.assertEqual(app.settings.top_p, 1.0)
            self.assertEqual(app.session.candidates, (candidate(1),))
            self.assertFalse(app.config_path.exists())

            app._handle_key("a")

            self.assertEqual(app.settings.top_p, 0.95)
            self.assertEqual(app.session.replace_settings_calls[-1].top_p, 0.95)
            self.assertEqual(app.session.candidates, ())
            self.assertIsNone(app._operations.current_take)
            self.assertEqual(
                json.loads(app.config_path.read_text())["top_p"],
                0.95,
            )
            app._operations.stop_playback.assert_called_once_with()

    def test_settings_apply_reconciles_session_state_before_candidate_invalidation(self):
        app = self.make_app(query=mixed_query(), candidates=(candidate(1),))
        target = Settings(
            top_p=0.95,
            output_dir=app.settings.output_dir,
        )
        app.settings = target
        app._persisted_settings = target
        app._operations.current_take = 1
        app._operations.stop_playback = Mock()
        app._open_settings_editor()

        with patch("voiceger_editor.tui.save_settings") as save:
            app._handle_key("a")

        save.assert_called_once_with(target, app.config_path)
        self.assertEqual(app.session.replace_settings_calls, [target])
        self.assertEqual(app.session.candidates, ())
        self.assertIsNone(app._operations.current_take)
        app._operations.stop_playback.assert_called_once_with()

    def test_explicit_settings_save_persists_entire_cli_effective_target(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "settings.json"
            effective = Settings(
                style_id=22,
                speed=1.25,
                take_count=7,
                output_dir=Path("/tmp/effective-output"),
                save_text=True,
            )
            persisted = Settings(output_dir=Path("/tmp/config-output"))
            app = TuiApp(
                adapter=Mock(),
                settings=effective,
                persisted_settings=persisted,
                config_path=config_path,
            )
            app.session = FakeSession(query=mixed_query(), candidates=(candidate(1),))
            app.session.settings = effective
            app._batch.batch.add_item(CaptionBatchItem(app.session))
            app._batch.open_item(0)
            app._open_settings_editor()
            editor = app._editor_controller.editor
            editor.payload["draft_settings"]["output_dir"] = "/tmp/explicit-output"
            editor.selection = "apply"

            app._handle_key("\n")

            target = Settings(
                style_id=22,
                speed=1.25,
                take_count=7,
                output_dir=Path("/tmp/explicit-output"),
                save_text=True,
            )
            self.assertEqual(app.session.replace_settings_calls, [target])
            self.assertEqual(app._persisted_settings, target)
            self.assertEqual(json.loads(config_path.read_text()), {
                "output_dir": "/tmp/explicit-output",
                "filename_template": target.filename_template,
                "output_format": target.output_format,
                "wav_encoding": target.wav_encoding,
                "flac_encoding": target.flac_encoding,
                "mp3_bitrate": target.mp3_bitrate,
                "take_count": 7,
                "style_id": 22,
                "speed": 1.25,
                "top_k": 20,
                "top_p": 1.0,
                "temperature": 1.0,
                "save_text": True,
                "save_lab": False,
            })
